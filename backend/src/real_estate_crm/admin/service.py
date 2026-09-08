from __future__ import annotations

import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from real_estate_crm.auth.models import AuditEvent, LeadStatusHistory, User, audit_context
from real_estate_crm.leads.models import ConsentRecord, Contact, Inquiry, Property

INQUIRY_STATUSES = frozenset({"new", "contacted", "qualified", "viewing", "won", "lost", "closed"})


class InquiryNotFound(LookupError):
    pass


class StaleInquiryVersion(RuntimeError):
    pass


class InvalidInquiryMutation(ValueError):
    pass


class InvalidCursor(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class InquiryFilters:
    status: str | None = None
    property_id: uuid.UUID | None = None
    assigned_user_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if self.status is not None and self.status not in INQUIRY_STATUSES:
            raise ValueError("unsupported inquiry status")


@dataclass(frozen=True, slots=True)
class InquiryPage:
    items: list[dict[str, Any]]
    next_cursor: str | None


def _encode_cursor(submitted_at: datetime, inquiry_id: uuid.UUID) -> str:
    payload = json.dumps(
        [submitted_at.astimezone(timezone.utc).isoformat(), str(inquiry_id)],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()


def _decode_cursor(value: str) -> tuple[datetime, uuid.UUID]:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise InvalidCursor("invalid cursor")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        decoded = json.loads(raw)
        if not isinstance(decoded, list) or len(decoded) != 2 or not all(isinstance(item, str) for item in decoded):
            raise ValueError
        submitted_at = datetime.fromisoformat(decoded[0])
        if submitted_at.tzinfo is None or submitted_at.utcoffset() is None:
            raise ValueError
        return submitted_at.astimezone(timezone.utc), uuid.UUID(decoded[1])
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise InvalidCursor("invalid cursor") from exc


class AdminService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def list_inquiries(
        self,
        *,
        page_size: int = 25,
        cursor: str | None = None,
        filters: InquiryFilters = InquiryFilters(),
    ) -> InquiryPage:
        if not 1 <= page_size <= 100:
            raise ValueError("page size must be between 1 and 100")
        columns = (
            Inquiry.id,
            Inquiry.public_reference,
            Inquiry.status,
            Inquiry.version,
            Inquiry.source_platform,
            Inquiry.intent,
            Inquiry.submitted_at,
            Inquiry.assigned_user_id,
            Contact.full_name,
            Contact.normalized_email,
            Contact.normalized_phone,
            Property.id.label("property_id"),
            Property.title.label("property_title"),
            User.display_name.label("assignee_name"),
        )
        query = (
            sa.select(*columns)
            .join(Contact, Inquiry.contact_id == Contact.id)
            .join(Property, Inquiry.property_id == Property.id)
            .outerjoin(User, Inquiry.assigned_user_id == User.id)
            .order_by(Inquiry.submitted_at.desc(), Inquiry.id.desc())
            .limit(page_size + 1)
        )
        if filters.status:
            query = query.where(Inquiry.status == filters.status)
        if filters.property_id:
            query = query.where(Inquiry.property_id == filters.property_id)
        if filters.assigned_user_id:
            query = query.where(Inquiry.assigned_user_id == filters.assigned_user_id)
        if cursor:
            submitted_at, inquiry_id = _decode_cursor(cursor)
            query = query.where(
                sa.or_(
                    Inquiry.submitted_at < submitted_at,
                    sa.and_(Inquiry.submitted_at == submitted_at, Inquiry.id < inquiry_id),
                )
            )
        with self._sessions() as session:
            rows = session.execute(query).mappings().all()
        visible = rows[:page_size]
        items = [self._summary(dict(row)) for row in visible]
        next_cursor = (
            _encode_cursor(visible[-1]["submitted_at"], visible[-1]["id"])
            if len(rows) > page_size and visible
            else None
        )
        return InquiryPage(items, next_cursor)

    def get_inquiry(self, inquiry_id: uuid.UUID) -> dict[str, Any]:
        query = (
            sa.select(
                Inquiry,
                Contact,
                Property,
                User.display_name.label("assignee_name"),
                ConsentRecord.notice_version,
                ConsentRecord.requested_contact,
                ConsentRecord.marketing_opt_in,
                ConsentRecord.ad_measurement_opt_in,
                ConsentRecord.recorded_at,
            )
            .join(Contact, Inquiry.contact_id == Contact.id)
            .join(Property, Inquiry.property_id == Property.id)
            .outerjoin(User, Inquiry.assigned_user_id == User.id)
            .outerjoin(ConsentRecord, Inquiry.id == ConsentRecord.inquiry_id)
            .where(Inquiry.id == inquiry_id)
        )
        with self._sessions() as session:
            row = session.execute(query).one_or_none()
            if row is None:
                raise InquiryNotFound("inquiry not found")
            inquiry, contact, prop = row[0], row[1], row[2]
            history = session.execute(
                sa.select(
                    LeadStatusHistory.id,
                    LeadStatusHistory.from_status,
                    LeadStatusHistory.to_status,
                    LeadStatusHistory.created_at,
                    LeadStatusHistory.actor_user_id,
                    User.display_name.label("actor_name"),
                )
                .join(User, LeadStatusHistory.actor_user_id == User.id)
                .where(LeadStatusHistory.inquiry_id == inquiry_id)
                .order_by(LeadStatusHistory.created_at, LeadStatusHistory.id)
            ).mappings()
            return {
                **self._summary(
                    {
                        "id": inquiry.id,
                        "public_reference": inquiry.public_reference,
                        "status": inquiry.status,
                        "version": inquiry.version,
                        "source_platform": inquiry.source_platform,
                        "intent": inquiry.intent,
                        "submitted_at": inquiry.submitted_at,
                        "assigned_user_id": inquiry.assigned_user_id,
                        "full_name": contact.full_name,
                        "normalized_email": contact.normalized_email,
                        "normalized_phone": contact.normalized_phone,
                        "property_id": prop.id,
                        "property_title": prop.title,
                        "assignee_name": row.assignee_name,
                    }
                ),
                "captureSurface": inquiry.capture_surface,
                "formVersion": inquiry.form_version,
                "budgetBand": inquiry.budget_band,
                "timeframe": inquiry.timeframe,
                "preferredContactMethod": inquiry.preferred_contact_method,
                "message": inquiry.message,
                "dedupeState": inquiry.dedupe_state,
                "updatedAt": inquiry.updated_at.isoformat(),
                "consent": (
                    {
                        "noticeVersion": row.notice_version,
                        "requestedContact": row.requested_contact,
                        "marketing": row.marketing_opt_in,
                        "adMeasurement": row.ad_measurement_opt_in,
                        "recordedAt": row.recorded_at.isoformat(),
                    }
                    if row.notice_version is not None
                    else None
                ),
                "statusHistory": [
                    {
                        "id": str(item.id),
                        "fromStatus": item.from_status,
                        "toStatus": item.to_status,
                        "createdAt": item.created_at.isoformat(),
                        "actor": {"id": str(item.actor_user_id), "displayName": item.actor_name},
                    }
                    for item in history
                ],
            }

    def list_active_users(self) -> list[dict[str, str]]:
        with self._sessions() as session:
            rows = session.execute(
                sa.select(User.id, User.display_name, User.role)
                .where(User.is_active.is_(True))
                .order_by(sa.func.lower(User.display_name), User.id)
            ).all()
        return [{"id": str(row.id), "displayName": row.display_name, "role": row.role} for row in rows]

    def update_status(
        self,
        inquiry_id: uuid.UUID,
        *,
        status: str,
        expected_version: int,
        actor_user_id: uuid.UUID,
        request_id: uuid.UUID,
    ) -> dict[str, Any]:
        if status not in INQUIRY_STATUSES:
            raise InvalidInquiryMutation("unsupported inquiry status")
        with self._sessions() as session, session.begin():
            current = session.execute(
                sa.select(Inquiry.status, Inquiry.version).where(Inquiry.id == inquiry_id)
            ).one_or_none()
            self._validate_mutation(current, expected_version)
            assert current is not None
            old_status = current.status
            if old_status == status:
                raise InvalidInquiryMutation("status must change")
            changed = self._cas_update(session, inquiry_id, expected_version, status=status)
            if not changed:
                raise StaleInquiryVersion("inquiry changed concurrently")
            session.add_all(
                [
                    LeadStatusHistory(
                        id=uuid.uuid4(),
                        inquiry_id=inquiry_id,
                        actor_user_id=actor_user_id,
                        from_status=old_status,
                        to_status=status,
                    ),
                    self._audit(
                        inquiry_id,
                        actor_user_id,
                        request_id,
                        "inquiry.status.changed",
                        {"from_status": old_status, "to_status": status},
                    ),
                ]
            )
        return self.get_inquiry(inquiry_id)

    def update_assignment(
        self,
        inquiry_id: uuid.UUID,
        *,
        assigned_user_id: uuid.UUID | None,
        expected_version: int,
        actor_user_id: uuid.UUID,
        request_id: uuid.UUID,
    ) -> dict[str, Any]:
        with self._sessions() as session, session.begin():
            if assigned_user_id is not None:
                active = session.scalar(sa.select(User.is_active).where(User.id == assigned_user_id))
                if active is not True:
                    raise InvalidInquiryMutation("assignee must be an active user")
            current = session.execute(
                sa.select(Inquiry.assigned_user_id, Inquiry.version).where(Inquiry.id == inquiry_id)
            ).one_or_none()
            self._validate_mutation(current, expected_version)
            assert current is not None
            old_assignee = current.assigned_user_id
            if old_assignee == assigned_user_id:
                raise InvalidInquiryMutation("assignment must change")
            changed = self._cas_update(
                session, inquiry_id, expected_version, assigned_user_id=assigned_user_id
            )
            if not changed:
                raise StaleInquiryVersion("inquiry changed concurrently")
            session.add(
                self._audit(
                    inquiry_id,
                    actor_user_id,
                    request_id,
                    "inquiry.assignment.changed",
                    {
                        "from_assignee_id": str(old_assignee) if old_assignee else None,
                        "to_assignee_id": str(assigned_user_id) if assigned_user_id else None,
                    },
                )
            )
        return self.get_inquiry(inquiry_id)

    @staticmethod
    def _validate_mutation(current: Any, expected_version: int) -> None:
        if expected_version < 1:
            raise InvalidInquiryMutation("expected version must be positive")
        if current is None:
            raise InquiryNotFound("inquiry not found")
        if current.version != expected_version:
            raise StaleInquiryVersion("inquiry version is stale")

    @staticmethod
    def _cas_update(session: Session, inquiry_id: uuid.UUID, expected_version: int, **values: Any) -> bool:
        result = session.execute(
            sa.update(Inquiry)
            .where(Inquiry.id == inquiry_id, Inquiry.version == expected_version)
            .values(**values, version=Inquiry.version + 1, updated_at=sa.func.now())
        )
        return bool(result.rowcount == 1)  # type: ignore[attr-defined]

    @staticmethod
    def _audit(
        inquiry_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        request_id: uuid.UUID,
        action: str,
        context: dict[str, str | None],
    ) -> AuditEvent:
        return AuditEvent(
            id=uuid.uuid4(),
            actor_user_id=actor_user_id,
            action=action,
            entity_type="inquiry",
            entity_id=inquiry_id,
            request_id=request_id,
            context=audit_context(context),
        )

    @staticmethod
    def _summary(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "reference": row["public_reference"],
            "status": row["status"],
            "version": row["version"],
            "sourcePlatform": row["source_platform"],
            "intent": row["intent"],
            "submittedAt": row["submitted_at"].isoformat(),
            "contact": {
                "fullName": row["full_name"],
                "email": row["normalized_email"],
                "phone": row["normalized_phone"],
            },
            "property": {"id": str(row["property_id"]), "title": row["property_title"]},
            "assignee": (
                {"id": str(row["assigned_user_id"]), "displayName": row["assignee_name"]}
                if row["assigned_user_id"]
                else None
            ),
        }


__all__ = [
    "AdminService",
    "INQUIRY_STATUSES",
    "InquiryFilters",
    "InquiryNotFound",
    "InquiryPage",
    "InvalidCursor",
    "InvalidInquiryMutation",
    "StaleInquiryVersion",
]
