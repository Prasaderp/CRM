from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from real_estate_crm.leads.models import IdempotencyRequest, OutboxJob
from real_estate_crm.notifications.email import DeliveryResult
from real_estate_crm.notifications.worker import (
    CLEANUP_LIMIT,
    NotificationWorker,
    WorkerStore,
    retry_delay,
)

NOW = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def committed_factory(test_engine: sa.Engine):
    factory = sessionmaker(test_engine, expire_on_commit=False)
    yield factory
    with factory.begin() as session:
        session.execute(sa.delete(OutboxJob).where(OutboxJob.dedupe_key.like("phase9:%")))
        session.execute(sa.delete(IdempotencyRequest).where(IdempotencyRequest.endpoint == "/phase9-test"))


def _add_jobs(factory: sessionmaker[Session], count: int, **overrides: object) -> list[uuid.UUID]:
    ids = [uuid.uuid4() for _ in range(count)]
    with factory.begin() as session:
        jobs = []
        for job_id in ids:
            values: dict[str, object] = {
                "id": job_id,
                "job_kind": "lead_email",
                "aggregate_id": uuid.uuid4(),
                "dedupe_key": f"phase9:{job_id}",
                "payload": {"inquiryId": str(uuid.uuid4()), "propertyId": str(uuid.uuid4())},
                "state": "pending",
                "attempts": 0,
                "available_at": NOW,
                "created_at": NOW,
            }
            values.update(overrides)
            jobs.append(OutboxJob(**values))
        session.add_all(jobs)
    return ids


def test_two_workers_exclude_claims_and_cap_batch(committed_factory: sessionmaker[Session]) -> None:
    ids = set(_add_jobs(committed_factory, 25))
    first = WorkerStore(committed_factory, clock=lambda: NOW).claim("worker-a", limit=20)
    second = WorkerStore(committed_factory, clock=lambda: NOW).claim("worker-b", limit=20)
    assert len(first) == 20 and len(second) == 5
    assert {job.id for job in first}.isdisjoint(job.id for job in second)
    assert {job.id for job in first + second} == ids
    with committed_factory() as session:
        assert not session.in_transaction()
        assert set(session.scalars(sa.select(OutboxJob.locked_by).where(OutboxJob.id.in_(ids)))) == {
            "worker-a",
            "worker-b",
        }


def test_stale_recovery_and_old_owner_cannot_complete(committed_factory: sessionmaker[Session]) -> None:
    (job_id,) = _add_jobs(committed_factory, 1)
    original = WorkerStore(committed_factory, clock=lambda: NOW).claim("worker-a")[0]
    reclaimed_at = NOW + timedelta(minutes=2, seconds=1)
    replacement_store = WorkerStore(committed_factory, clock=lambda: reclaimed_at)
    replacement = replacement_store.claim("worker-b")[0]
    assert replacement.id == job_id and replacement.attempts == 2
    assert not WorkerStore(committed_factory, clock=lambda: reclaimed_at).record(
        "worker-a", original, DeliveryResult.sent(f"<{job_id}@example.test>")
    )
    assert replacement_store.record("worker-b", replacement, DeliveryResult.transient("smtp_timeout"))
    with committed_factory() as session:
        row = session.get(OutboxJob, job_id)
        assert row is not None and row.state == "pending" and row.locked_by is None
        assert reclaimed_at + timedelta(seconds=30) <= row.available_at <= reclaimed_at + timedelta(seconds=90)


@pytest.mark.parametrize(
    ("attempt", "random_value", "seconds"),
    [(1, 0.0, 15), (1, 1.0, 45), (11, 0.0, 10_800), (12, 1.0, 32_400)],
)
def test_retry_delay_bounds(attempt: int, random_value: float, seconds: int) -> None:
    assert retry_delay(attempt, random_value) == timedelta(seconds=seconds)


def test_attempt_and_age_limits_become_dead_without_delivery(committed_factory: sessionmaker[Session]) -> None:
    maxed = _add_jobs(committed_factory, 1, attempts=12)[0]
    aged = _add_jobs(committed_factory, 1, created_at=NOW - timedelta(hours=24, seconds=1))[0]
    assert WorkerStore(committed_factory, clock=lambda: NOW).claim("worker-a") == []
    with committed_factory() as session:
        rows = list(session.scalars(sa.select(OutboxJob).where(OutboxJob.id.in_([maxed, aged]))))
        assert all(row.state == "dead" and row.last_error_code == "delivery_limits_exceeded" for row in rows)


def test_cleanup_is_bounded_and_expired_only(committed_factory: sessionmaker[Session]) -> None:
    with committed_factory.begin() as session:
        session.add_all(
            [
                IdempotencyRequest(
                    endpoint="/phase9-test",
                    key=uuid.uuid4(),
                    request_sha256=b"x" * 32,
                    created_at=NOW - timedelta(hours=49),
                    expires_at=NOW - timedelta(hours=1),
                )
                for _ in range(CLEANUP_LIMIT + 1)
            ]
            + [
                IdempotencyRequest(
                    endpoint="/phase9-test",
                    key=uuid.uuid4(),
                    request_sha256=b"y" * 32,
                    created_at=NOW,
                    expires_at=NOW + timedelta(hours=48),
                )
            ]
        )
    store = WorkerStore(committed_factory, clock=lambda: NOW)
    assert store.cleanup_expired_idempotency() == CLEANUP_LIMIT
    assert store.cleanup_expired_idempotency() == 1
    with committed_factory() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(IdempotencyRequest).where(IdempotencyRequest.endpoint == "/phase9-test")
        ) == 1


def test_worker_honors_preexisting_cancellation_without_database_or_smtp() -> None:
    stopped = threading.Event()
    stopped.set()
    store, email, settings = Mock(), Mock(), Mock()
    NotificationWorker(store, email, settings, "worker-a", stop_event=stopped).run()
    store.claim.assert_not_called()
    email.deliver.assert_not_called()


def test_handler_runs_after_claim_transaction_and_dispatches_typed_result(
    committed_factory: sessionmaker[Session],
) -> None:
    _add_jobs(committed_factory, 1)
    store = WorkerStore(committed_factory, clock=lambda: NOW)
    job = store.claim("worker-a")[0]
    email = Mock()
    email.deliver.return_value = DeliveryResult.sent(f"<{job.id}@example.test>")
    worker = NotificationWorker(store, email, Mock(), "worker-a", stop_event=threading.Event(), clock=lambda: NOW)
    worker._handle([job])
    email.deliver.assert_called_once_with(job.id, job.aggregate_id, job.payload)
    with committed_factory() as session:
        row = session.get(OutboxJob, job.id)
        assert row is not None and row.state == "completed" and row.completed_at == NOW


def test_post_send_crash_is_reclaimable_and_duplicate_observable(committed_factory: sessionmaker[Session]) -> None:
    _add_jobs(committed_factory, 1)
    first = WorkerStore(committed_factory, clock=lambda: NOW).claim("crashed-worker")[0]
    later = NOW + timedelta(minutes=3)
    second = WorkerStore(committed_factory, clock=lambda: later).claim("replacement-worker")[0]
    assert second.id == first.id and second.attempts == 2
    assert WorkerStore(committed_factory, clock=lambda: later).record(
        "replacement-worker", second, DeliveryResult.sent(f"<{second.id}@example.test>")
    )


def test_malformed_claim_arguments_fail_closed(committed_factory: sessionmaker[Session]) -> None:
    store = WorkerStore(committed_factory, clock=lambda: NOW)
    for worker_id, limit in [("", 1), ("x", 0), ("x", 21)]:
        with pytest.raises(ValueError):
            store.claim(worker_id, limit=limit)
