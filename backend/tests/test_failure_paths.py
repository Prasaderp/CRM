from __future__ import annotations

import io
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from factories import make_property
from real_estate_crm.app import create_app
from real_estate_crm.auth.models import User
from real_estate_crm.auth.service import AuthService
from real_estate_crm.config import get_settings
from real_estate_crm.db import DatabaseError
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
from real_estate_crm.leads.service import LeadService
from real_estate_crm.notifications.email import DeliveryDisposition, EmailAdapter
from real_estate_crm.notifications.worker import WorkerStore
from real_estate_crm.observability import ReadinessProbe, configure_logging, safe_event

NOW = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)


def _lead(slug: str, email: str = "failure-path@example.com"):
    return normalize_lead(
        LeadRequest.model_validate(
            {
                "propertySlug": slug,
                "formVersion": "failure-gate-v1",
                "contact": {
                    "fullName": "Synthetic Failure Gate",
                    "email": email,
                    "preferredContactMethod": "email",
                },
                "inquiry": {"intent": "information", "message": "Synthetic test record."},
                "consent": {
                    "privacyNoticeVersion": "untrusted-version",
                    "requestedContact": True,
                    "marketing": False,
                    "adMeasurement": False,
                },
            }
        )
    )


@pytest.fixture
def release_store(test_engine: sa.Engine):
    factory = sessionmaker(test_engine, expire_on_commit=False)
    property_id = uuid.uuid4()
    slug = f"failure-gate-{property_id.hex[:12]}"
    with factory.begin() as session:
        session.add(Property(**make_property(id=property_id, slug=slug)))
    yield factory, LeadService(factory, get_settings(), clock=lambda: NOW), property_id, slug
    with factory.begin() as session:
        inquiry_ids = list(session.scalars(sa.select(Inquiry.id).where(Inquiry.property_id == property_id)))
        contact_ids = list(session.scalars(sa.select(Inquiry.contact_id).where(Inquiry.id.in_(inquiry_ids))))
        session.execute(sa.delete(OutboxJob).where(OutboxJob.aggregate_id.in_(inquiry_ids)))
        session.execute(sa.delete(IdempotencyRequest).where(IdempotencyRequest.inquiry_id.in_(inquiry_ids)))
        session.execute(sa.delete(AttributionTouch).where(AttributionTouch.inquiry_id.in_(inquiry_ids)))
        session.execute(sa.delete(ConsentRecord).where(ConsentRecord.inquiry_id.in_(inquiry_ids)))
        session.execute(sa.delete(Inquiry).where(Inquiry.id.in_(inquiry_ids)))
        session.execute(sa.delete(Contact).where(Contact.id.in_(contact_ids)))
        session.execute(sa.delete(Property).where(Property.id == property_id))


class _UnavailableLeadService:
    def accept(self, _lead: object, _key: uuid.UUID) -> object:
        raise DatabaseError("postgresql://user:secret@private-host/customer@example.test")

    def get_property(self, _slug: str) -> object:
        raise DatabaseError("private database address")


def test_database_outage_never_reports_success_while_liveness_survives() -> None:
    app = create_app(
        settings=get_settings(),
        session_factory=sessionmaker(class_=Session),
        service_factory=lambda _factory, _settings: _UnavailableLeadService(),  # type: ignore[arg-type,return-value]
        readiness_probe=lambda: (False, "database_unavailable"),
    )
    payload = {
        "propertySlug": "failure-gate-home",
        "formVersion": "failure-gate-v1",
        "contact": {"fullName": "Synthetic User", "email": "customer@example.com"},
        "consent": {
            "privacyNoticeVersion": "test",
            "requestedContact": True,
            "marketing": False,
            "adMeasurement": False,
        },
    }
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/leads",
            json=payload,
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 503 and response.json()["error"]["code"] == "service_unavailable"
        assert "customer@example.com" not in response.text and "private-host" not in response.text
        assert client.get("/health/live").status_code == 200
        readiness = client.get("/health/ready")
        assert readiness.status_code == 503 and readiness.json()["reason"] == "database_unavailable"


class _ControlledSMTP:
    fail = True
    messages: list[EmailMessage] = []

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def __enter__(self) -> _ControlledSMTP:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def send_message(self, message: EmailMessage) -> None:
        if self.fail:
            raise ConnectionRefusedError("synthetic SMTP outage")
        self.messages.append(message)


def test_smtp_outage_recovery_and_post_send_crash_preserve_durable_jobs(
    release_store: tuple[sessionmaker[Session], LeadService, uuid.UUID, str],
) -> None:
    factory, service, _, slug = release_store
    _ControlledSMTP.fail, _ControlledSMTP.messages = True, []
    accepted, replay = service.accept(_lead(slug), uuid.uuid4())
    assert not replay
    store = WorkerStore(factory, clock=lambda: NOW, random_value=lambda: 0)
    job = store.claim("outage-worker")[0]
    # This test covers outbox durability, not transport security; pin the plain
    # transport so it does not depend on the ambient SMTP_SECURITY value.
    plain = get_settings().model_copy(update={"smtp_security": "none"})
    adapter = EmailAdapter(factory, plain, smtp_factory=_ControlledSMTP)
    failed = adapter.deliver(job.id, job.aggregate_id, job.payload)
    assert failed.disposition is DeliveryDisposition.TRANSIENT
    assert store.record("outage-worker", job, failed)
    with factory() as session:
        assert session.get(Inquiry, accepted.inquiry_id) is not None
        durable = session.get(OutboxJob, job.id)
        assert durable is not None and durable.state == "pending" and durable.attempts == 1

    _ControlledSMTP.fail = False
    recovery_time = NOW + timedelta(seconds=16)
    recovery_store = WorkerStore(factory, clock=lambda: recovery_time)
    recovered = recovery_store.claim("recovery-worker")[0]
    sent = adapter.deliver(recovered.id, recovered.aggregate_id, recovered.payload)
    assert sent.disposition is DeliveryDisposition.SENT
    assert recovery_store.record("recovery-worker", recovered, sent)

    second, _ = service.accept(_lead(slug, "post-send-crash@example.com"), uuid.uuid4())
    crash_time = recovery_time + timedelta(seconds=1)
    crash_store = WorkerStore(factory, clock=lambda: crash_time)
    claimed = crash_store.claim("crashed-worker")[0]
    first_delivery = adapter.deliver(claimed.id, claimed.aggregate_id, claimed.payload)
    replacement_time = crash_time + timedelta(minutes=2, seconds=1)
    replacement_store = WorkerStore(factory, clock=lambda: replacement_time)
    reclaimed = replacement_store.claim("replacement-worker")[0]
    duplicate_delivery = adapter.deliver(reclaimed.id, reclaimed.aggregate_id, reclaimed.payload)
    assert reclaimed.aggregate_id == second.inquiry_id and reclaimed.attempts == 2
    assert first_delivery.message_id == duplicate_delivery.message_id
    assert replacement_store.record("replacement-worker", reclaimed, duplicate_delivery)


def test_concurrent_same_key_commits_one_complete_lead(
    release_store: tuple[sessionmaker[Session], LeadService, uuid.UUID, str],
) -> None:
    factory, service, _, slug = release_store
    key, barrier = uuid.uuid4(), threading.Barrier(2)

    def submit() -> tuple[uuid.UUID, bool]:
        barrier.wait(timeout=5)
        accepted, replayed = service.accept(_lead(slug, "concurrent-key@example.com"), key)
        return accepted.inquiry_id, replayed

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=10) for future in [pool.submit(submit), pool.submit(submit)]]
    assert results[0][0] == results[1][0] and {result[1] for result in results} == {False, True}
    inquiry_id = results[0][0]
    with factory() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(Inquiry).where(Inquiry.id == inquiry_id)) == 1
        assert session.scalar(
            sa.select(sa.func.count()).select_from(OutboxJob).where(OutboxJob.aggregate_id == inquiry_id)
        ) == 1
        idempotency = session.get(IdempotencyRequest, ("/api/v1/leads", key))
        assert idempotency is not None and idempotency.response_status == 201


def test_session_expiry_and_logs_fail_closed_without_sensitive_context(test_engine: sa.Engine) -> None:
    factory = sessionmaker(test_engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    clock = [NOW]
    auth = AuthService(factory, clock=lambda: clock[0])
    user = auth.create_user(
        f"expiry-{user_id.hex[:12]}@example.com",
        "Synthetic Expiry User",
        "a sufficiently long synthetic password",
        "agent",
    )
    issued = auth.issue_session(user.id)
    assert auth.lookup_session(issued.token) is not None
    clock[0] += timedelta(minutes=30)
    assert auth.lookup_session(issued.token) is None

    output = io.StringIO()
    configure_logging(stream=output)
    safe_event(
        "email.retry_scheduled",
        job_id=str(uuid.uuid4()),
        attempt=1,
        reason="smtp_timeout",
        email="customer@example.test",
        password="smtp-secret",
    )
    event = json.loads(output.getvalue())
    assert event["reason"] == "smtp_timeout"
    assert "customer@example.test" not in output.getvalue() and "smtp-secret" not in output.getvalue()
    with factory.begin() as session:
        session.execute(sa.delete(User).where(User.id == user.id))


def test_readiness_rejects_schema_drift_without_consulting_smtp() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", poolclass=sa.pool.StaticPool)
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO alembic_version VALUES ('0002_admin_auth')"))
    probe = ReadinessProbe(sessionmaker(engine), frozenset({"future_head"}))
    assert probe() == (False, "migration_mismatch")
