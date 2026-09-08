from __future__ import annotations

import base64
import hashlib
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from real_estate_crm.config import Settings
from real_estate_crm.db import DatabaseError
from real_estate_crm.leads.consent import build_consent_snapshot
from real_estate_crm.leads.models import AttributionTouch, ConsentRecord, Contact, IdempotencyRequest, Inquiry, OutboxJob, Property
from real_estate_crm.leads.normalization import NormalizedLead, request_sha256
from real_estate_crm.leads.schemas import LeadAccepted

LEAD_ENDPOINT = "/api/v1/leads"


class LeadServiceError(Exception):
    pass


class IdempotencyConflict(LeadServiceError):
    pass


class PropertyNotFound(LeadServiceError):
    pass


class IdempotencyStateError(LeadServiceError):
    pass


class LeadService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        *,
        clock: Callable[[], datetime] | None = None,
        uuid_factory: Callable[[], uuid.UUID] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._uuid = uuid_factory or uuid.uuid4

    def accept(self, lead: NormalizedLead, idempotency_key: uuid.UUID) -> tuple[LeadAccepted, bool]:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        digest = request_sha256(lead)
        try:
            with self._session_factory() as session, session.begin():
                idempotency = self._claim_idempotency(session, idempotency_key, digest, now)
                if idempotency.response_body is not None:
                    return LeadAccepted.model_validate(idempotency.response_body), True
                self._lock_contact_keys(session, lead)
                property_row = session.scalar(
                    sa.select(Property).where(Property.slug == lead.property_slug, Property.is_active.is_(True))
                )
                if property_row is None:
                    raise PropertyNotFound
                contact, dedupe_state = self._resolve_contact(session, lead)
                inquiry_id = self._uuid()
                accepted = LeadAccepted.model_validate(
                    {
                        "inquiryId": inquiry_id,
                        "reference": self._reference(inquiry_id),
                        "status": "new",
                        "submittedAt": now,
                    }
                )
                inquiry = Inquiry(
                    id=inquiry_id,
                    public_reference=accepted.reference,
                    contact_id=contact.id,
                    property_id=property_row.id,
                    source_platform=self._source_platform(lead.attribution.utm_source),
                    capture_surface="website",
                    form_version=lead.form_version,
                    intent=lead.intent.value if lead.intent else None,
                    budget_band=lead.budget_band.value if lead.budget_band else None,
                    timeframe=lead.timeframe.value if lead.timeframe else None,
                    preferred_contact_method=(lead.preferred_contact_method.value if lead.preferred_contact_method else None),
                    message=lead.message,
                    status="new",
                    dedupe_state=dedupe_state,
                    submitted_at=now,
                    updated_at=now,
                )
                snapshot = build_consent_snapshot(lead, self._settings, recorded_at=now)
                session.add_all(
                    [
                        inquiry,
                        ConsentRecord(inquiry_id=inquiry_id, **asdict(snapshot)),
                        AttributionTouch(
                            id=self._uuid(),
                            inquiry_id=inquiry_id,
                            touch_type="submission",
                            **lead.attribution.model_dump(mode="python"),
                            captured_at=now,
                        ),
                        OutboxJob(
                            id=self._uuid(),
                            job_kind="lead_email",
                            aggregate_id=inquiry_id,
                            dedupe_key=f"lead_email:{inquiry_id}",
                            payload={"inquiryId": str(inquiry_id), "propertyId": str(property_row.id)},
                            state="pending",
                            attempts=0,
                            available_at=now,
                            created_at=now,
                        ),
                    ]
                )
                response_body = accepted.model_dump(mode="json", by_alias=True)
                idempotency.inquiry_id = inquiry_id
                idempotency.response_status = 201
                idempotency.response_body = response_body
                session.flush()
            return accepted, False
        except sa.exc.OperationalError as exc:
            raise DatabaseError("lead transaction unavailable") from exc

    def get_property(self, slug: str) -> Property | None:
        try:
            with self._session_factory() as session:
                row = session.scalar(sa.select(Property).where(Property.slug == slug, Property.is_active.is_(True)))
                if row is not None:
                    session.expunge(row)
                return row
        except sa.exc.OperationalError as exc:
            raise DatabaseError("property lookup unavailable") from exc

    def _claim_idempotency(
        self, session: Session, key: uuid.UUID, digest: bytes, now: datetime
    ) -> IdempotencyRequest:
        expires_at = now + timedelta(hours=self._settings.idempotency_expiry_hours)
        inserted = session.execute(
            insert(IdempotencyRequest)
            .values(endpoint=LEAD_ENDPOINT, key=key, request_sha256=digest, created_at=now, expires_at=expires_at)
            .on_conflict_do_nothing(index_elements=["endpoint", "key"])
            .returning(IdempotencyRequest.endpoint)
        ).scalar_one_or_none()
        row = session.get(IdempotencyRequest, (LEAD_ENDPOINT, key), with_for_update=inserted is None)
        if row is None:
            raise IdempotencyStateError("idempotency row disappeared")
        if inserted is not None:
            return row
        if row.expires_at <= now:
            row.request_sha256 = digest
            row.inquiry_id = None
            row.response_status = None
            row.response_body = None
            row.created_at = now
            row.expires_at = expires_at
            return row
        if row.request_sha256 != digest:
            raise IdempotencyConflict
        if row.response_status != 201 or row.response_body is None or row.inquiry_id is None:
            raise IdempotencyStateError("idempotency response is incomplete")
        return row

    @staticmethod
    def _lock_contact_keys(session: Session, lead: NormalizedLead) -> None:
        keys = [f"email:{lead.email}" if lead.email else None, f"phone:{lead.phone}" if lead.phone else None]
        for value in sorted(key for key in keys if key is not None):
            lock_id = int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big", signed=True)
            session.execute(sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})

    def _resolve_contact(self, session: Session, lead: NormalizedLead) -> tuple[Contact, str]:
        predicates = [
            Contact.normalized_email == lead.email if lead.email else None,
            Contact.normalized_phone == lead.phone if lead.phone else None,
        ]
        candidates = list(session.scalars(sa.select(Contact).where(sa.or_(*(p for p in predicates if p is not None)))))
        exact = [
            contact
            for contact in candidates
            if (lead.email is None or contact.normalized_email == lead.email)
            and (lead.phone is None or contact.normalized_phone == lead.phone)
        ]
        if len(exact) == 1:
            return exact[0], "clear"
        contact = Contact(
            id=self._uuid(),
            full_name=lead.full_name,
            normalized_email=lead.email,
            normalized_phone=lead.phone,
        )
        session.add(contact)
        return contact, "review" if candidates else "clear"

    @staticmethod
    def _source_platform(source: str | None) -> str:
        if not source:
            return "direct"
        normalized = source.lower()
        return normalized if normalized in {"facebook", "instagram", "tiktok", "x", "direct"} else "unknown"

    @staticmethod
    def _reference(inquiry_id: uuid.UUID) -> str:
        return "RE-" + base64.b32encode(inquiry_id.bytes).decode("ascii").rstrip("=")[:10]
