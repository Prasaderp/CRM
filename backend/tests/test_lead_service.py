from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from factories import make_contact, make_property
from real_estate_crm.config import get_settings
from real_estate_crm.leads.models import (
    AttributionTouch,
    ConsentRecord,
    Contact,
    IdempotencyRequest,
    Inquiry,
    OutboxJob,
    Property,
)
from real_estate_crm.leads.normalization import normalize_lead
from real_estate_crm.leads.schemas import LeadRequest
from real_estate_crm.leads.service import IdempotencyConflict, LeadService, PropertyNotFound

NOW = datetime(2026, 7, 31, 9, 30, tzinfo=timezone.utc)


def _lead(**changes: object):
    body: dict[str, object] = {
        "propertySlug": "phase-seven-home",
        "formVersion": "property-inquiry-1.0",
        "contact": {
            "fullName": "  Test   Person  ",
            "email": "PERSON@example.com",
            "phone": "+15551234567",
            "preferredContactMethod": "email",
        },
        "inquiry": {"intent": "buy", "message": " Arrange   a viewing "},
        "attribution": {
            "utmSource": "instagram",
            "clickIdKind": "fbclid",
            "clickIdValue": "opaque-click",
            "landingUrl": "https://leads.example/properties/phase-seven-home?secret=discarded",
        },
        "consent": {
            "privacyNoticeVersion": "untrusted-client-version",
            "requestedContact": True,
            "marketing": False,
            "adMeasurement": True,
        },
    }
    body.update(changes)
    return normalize_lead(LeadRequest.model_validate(body))


@pytest.fixture
def service(db_session: Session) -> LeadService:
    db_session.add(Property(**make_property(slug="phase-seven-home")))
    db_session.flush()
    factory = sessionmaker(bind=db_session.connection(), expire_on_commit=False)
    return LeadService(factory, get_settings(), clock=lambda: NOW)


def test_accepts_all_records_atomically_and_replays_exact_response(db_session: Session, service: LeadService) -> None:
    key = uuid.uuid4()
    accepted, replayed = service.accept(_lead(), key)
    replay, is_replay = service.accept(_lead(), key)

    assert not replayed and is_replay and replay == accepted
    inquiry = db_session.get(Inquiry, accepted.inquiry_id)
    assert inquiry and inquiry.source_platform == "instagram" and inquiry.dedupe_state == "clear"
    assert inquiry.message == "Arrange a viewing"
    consent = db_session.get(ConsentRecord, accepted.inquiry_id)
    assert consent and consent.notice_version == get_settings().canonical_notice_version
    assert consent.notice_text == get_settings().canonical_notice_text
    assert len(consent.notice_sha256) == 32 and consent.ad_measurement_opt_in
    touch = db_session.scalar(sa.select(AttributionTouch).where(AttributionTouch.inquiry_id == accepted.inquiry_id))
    assert touch and touch.landing_path.endswith("/properties/phase-seven-home") and "?" not in touch.landing_path
    jobs = list(db_session.scalars(sa.select(OutboxJob).where(OutboxJob.aggregate_id == accepted.inquiry_id)))
    assert len(jobs) == 1
    assert jobs[0].payload == {"inquiryId": str(accepted.inquiry_id), "propertyId": str(inquiry.property_id)}
    assert not ({"fullName", "email", "phone", "message"} & jobs[0].payload.keys())


def test_key_payload_conflict_has_no_side_effect(db_session: Session, service: LeadService) -> None:
    key = uuid.uuid4()
    service.accept(_lead(), key)
    changed = _lead(inquiry={"intent": "rent"})
    with pytest.raises(IdempotencyConflict):
        service.accept(changed, key)
    assert db_session.scalar(sa.select(sa.func.count()).select_from(Inquiry)) == 1
    assert db_session.scalar(sa.select(sa.func.count()).select_from(OutboxJob)) == 1


def test_exact_contact_reused_but_partial_identifier_collision_is_reviewed(
    db_session: Session, service: LeadService
) -> None:
    existing = Contact(**make_contact(email="PERSON@example.com", phone="+15551234567"))
    db_session.add(existing)
    db_session.flush()
    first, _ = service.accept(_lead(), uuid.uuid4())
    conflicting = _lead(
        contact={
            "fullName": "Different Person",
            "email": "PERSON@example.com",
            "phone": "+15557654321",
            "preferredContactMethod": "phone",
        }
    )
    second, _ = service.accept(conflicting, uuid.uuid4())
    assert db_session.get(Inquiry, first.inquiry_id).contact_id == existing.id  # type: ignore[union-attr]
    second_row = db_session.get(Inquiry, second.inquiry_id)
    assert second_row and second_row.contact_id != existing.id and second_row.dedupe_state == "review"


def test_inactive_property_rolls_back_idempotency_contact_and_outbox(db_session: Session, service: LeadService) -> None:
    prop = db_session.scalar(sa.select(Property).where(Property.slug == "phase-seven-home"))
    assert prop
    prop.is_active = False
    db_session.flush()
    with pytest.raises(PropertyNotFound):
        service.accept(_lead(), uuid.uuid4())
    for model in (Contact, Inquiry, ConsentRecord, AttributionTouch, OutboxJob, IdempotencyRequest):
        assert db_session.scalar(sa.select(sa.func.count()).select_from(model)) == 0


def test_outbox_failure_rolls_back_every_mutation(db_session: Session) -> None:
    db_session.add(Property(**make_property(slug="phase-seven-home")))
    db_session.flush()

    class RejectOutboxSession(Session):
        def flush(self, objects=None):  # type: ignore[no-untyped-def]
            if any(isinstance(row, OutboxJob) for row in self.new):
                raise sa.exc.IntegrityError("forced outbox failure", {}, RuntimeError("forced"))
            return super().flush(objects)

    factory = sessionmaker(bind=db_session.connection(), class_=RejectOutboxSession, expire_on_commit=False)
    failing = LeadService(factory, get_settings(), clock=lambda: NOW)
    with pytest.raises(sa.exc.IntegrityError):
        failing.accept(_lead(), uuid.uuid4())
    for model in (Contact, Inquiry, ConsentRecord, AttributionTouch, OutboxJob, IdempotencyRequest):
        assert db_session.scalar(sa.select(sa.func.count()).select_from(model)) == 0


def test_concurrent_submissions_serialize_contact_matching(test_engine: sa.Engine) -> None:
    slug, email = f"concurrent-{uuid.uuid4().hex[:12]}", f"parallel-{uuid.uuid4().hex}@example.com"
    property_id = uuid.uuid4()
    with test_engine.begin() as connection:
        connection.execute(sa.insert(Property), [make_property(id=property_id, slug=slug)])
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    service = LeadService(factory, get_settings(), clock=lambda: NOW)
    lead = _lead(
        propertySlug=slug,
        contact={"fullName": "Concurrent Person", "email": email, "phone": "+15559876543"},
    )
    def submit_concurrently(keys: list[uuid.UUID]) -> list[tuple[uuid.UUID, bool]]:
        barrier = Barrier(len(keys))

        def submit(key: uuid.UUID) -> tuple[uuid.UUID, bool]:
            barrier.wait(timeout=5)
            accepted, replayed = service.accept(lead, key)
            return accepted.inquiry_id, replayed

        with ThreadPoolExecutor(max_workers=len(keys)) as pool:
            futures = [pool.submit(submit, key) for key in keys]
            return [future.result(timeout=10) for future in futures]

    try:
        distinct = submit_concurrently([uuid.uuid4(), uuid.uuid4()])
        shared_key = uuid.uuid4()
        identical = submit_concurrently([shared_key, shared_key])
        assert identical[0][0] == identical[1][0] and {result[1] for result in identical} == {False, True}
        inquiry_ids = [result[0] for result in distinct] + [identical[0][0]]
        with Session(test_engine) as session:
            inquiries = list(session.scalars(sa.select(Inquiry).where(Inquiry.id.in_(inquiry_ids))))
            contacts = list(session.scalars(sa.select(Contact).where(Contact.normalized_email == email)))
            assert len(inquiries) == 3 and len(contacts) == 1
            assert {inquiry.contact_id for inquiry in inquiries} == {contacts[0].id}
            assert all(inquiry.dedupe_state == "clear" for inquiry in inquiries)
    finally:
        with test_engine.begin() as connection:
            inquiry_subquery = sa.select(Inquiry.id).where(Inquiry.property_id == property_id)
            connection.execute(sa.delete(OutboxJob).where(OutboxJob.aggregate_id.in_(inquiry_subquery)))
            connection.execute(sa.delete(IdempotencyRequest).where(IdempotencyRequest.inquiry_id.in_(inquiry_subquery)))
            connection.execute(sa.delete(AttributionTouch).where(AttributionTouch.inquiry_id.in_(inquiry_subquery)))
            connection.execute(sa.delete(ConsentRecord).where(ConsentRecord.inquiry_id.in_(inquiry_subquery)))
            connection.execute(sa.delete(Inquiry).where(Inquiry.property_id == property_id))
            connection.execute(sa.delete(Contact).where(Contact.normalized_email == email))
            connection.execute(sa.delete(Property).where(Property.id == property_id))
