from __future__ import annotations

import argparse
import random
import signal
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker
from typing import Any, cast

from real_estate_crm.config import Settings, get_settings
from real_estate_crm.db import get_session_factory
from real_estate_crm.leads.models import IdempotencyRequest, OutboxJob
from real_estate_crm.notifications.email import DeliveryDisposition, DeliveryResult, EmailAdapter

MAX_ATTEMPTS = 12
MAX_AGE = timedelta(hours=24)
MAX_BACKOFF = timedelta(hours=6)
CLEANUP_INTERVAL = timedelta(hours=1)
CLEANUP_LIMIT = 1_000
CLEANUP_ADVISORY_KEY = 734_624_190_921_001


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: uuid.UUID
    job_kind: str
    aggregate_id: uuid.UUID
    payload: dict[str, object]
    attempts: int
    created_at: datetime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def retry_delay(attempts: int, random_value: float) -> timedelta:
    if attempts < 1 or not 0 <= random_value <= 1:
        raise ValueError("invalid retry inputs")
    base_seconds = min(30 * 2 ** (attempts - 1), int(MAX_BACKOFF.total_seconds()))
    return timedelta(seconds=base_seconds * (0.5 + random_value))


class WorkerStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = utc_now,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._random = random_value

    def claim(self, worker_id: str, *, limit: int = 20, lease: timedelta = timedelta(minutes=2)) -> list[ClaimedJob]:
        if not worker_id or len(worker_id) > 200 or not 1 <= limit <= 20 or lease <= timedelta(0):
            raise ValueError("invalid claim parameters")
        now = self._aware_now()
        stale_before = now - lease
        reclaimable = sa.or_(
            sa.and_(OutboxJob.state == "pending", OutboxJob.available_at <= now),
            sa.and_(
                OutboxJob.state == "processing",
                sa.or_(OutboxJob.locked_at.is_(None), OutboxJob.locked_at <= stale_before),
            ),
        )
        terminal = sa.and_(reclaimable, sa.or_(OutboxJob.attempts >= MAX_ATTEMPTS, OutboxJob.created_at <= now - MAX_AGE))
        eligible = sa.and_(reclaimable, OutboxJob.attempts < MAX_ATTEMPTS, OutboxJob.created_at > now - MAX_AGE)
        with self._session_factory() as session, session.begin():
            terminal_ids = list(
                session.scalars(
                    sa.select(OutboxJob.id)
                    .where(terminal)
                    .order_by(OutboxJob.created_at, OutboxJob.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            session.execute(
                sa.update(OutboxJob)
                .where(OutboxJob.id.in_(terminal_ids))
                .values(state="dead", locked_by=None, locked_at=None, last_error_code="delivery_limits_exceeded")
            )
            rows = list(
                session.scalars(
                    sa.select(OutboxJob)
                    .where(eligible)
                    .order_by(OutboxJob.available_at, OutboxJob.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            for row in rows:
                row.state, row.locked_by, row.locked_at, row.attempts = "processing", worker_id, now, row.attempts + 1
            session.flush()
            return [
                ClaimedJob(row.id, row.job_kind, row.aggregate_id, dict(row.payload), row.attempts, row.created_at)
                for row in rows
            ]

    def record(self, worker_id: str, job: ClaimedJob, result: DeliveryResult) -> bool:
        now = self._aware_now()
        values: dict[str, object]
        if result.disposition is DeliveryDisposition.SENT:
            if result.message_id is None:
                raise ValueError("sent result requires message_id")
            values = {
                "state": "completed",
                "locked_by": None,
                "locked_at": None,
                "completed_at": now,
                "last_error_code": None,
                "smtp_message_id": result.message_id,
            }
        else:
            code = result.error_code or "unclassified_delivery_failure"
            dead = (
                result.disposition is DeliveryDisposition.TERMINAL
                or job.attempts >= MAX_ATTEMPTS
                or job.created_at <= now - MAX_AGE
            )
            values = {
                "state": "dead" if dead else "pending",
                "locked_by": None,
                "locked_at": None,
                "last_error_code": code[:80],
                "available_at": now if dead else now + retry_delay(job.attempts, self._random()),
            }
        with self._session_factory() as session, session.begin():
            changed = cast(CursorResult[Any], session.execute(
                sa.update(OutboxJob)
                .where(
                    OutboxJob.id == job.id,
                    OutboxJob.state == "processing",
                    OutboxJob.locked_by == worker_id,
                    OutboxJob.attempts == job.attempts,
                )
                .values(**values)
            )).rowcount
        return changed == 1

    def cleanup_expired_idempotency(self, *, limit: int = CLEANUP_LIMIT) -> int:
        if not 1 <= limit <= CLEANUP_LIMIT:
            raise ValueError("invalid cleanup limit")
        now = self._aware_now()
        with self._session_factory() as session, session.begin():
            acquired = session.scalar(sa.text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": CLEANUP_ADVISORY_KEY})
            if not acquired:
                return 0
            expired = (
                sa.select(IdempotencyRequest.endpoint, IdempotencyRequest.key)
                .where(IdempotencyRequest.expires_at <= now)
                .order_by(IdempotencyRequest.expires_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            return cast(CursorResult[Any], session.execute(
                sa.delete(IdempotencyRequest).where(
                    sa.tuple_(IdempotencyRequest.endpoint, IdempotencyRequest.key).in_(expired)
                )
            )).rowcount

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now


class NotificationWorker:
    def __init__(
        self,
        store: WorkerStore,
        email: EmailAdapter,
        settings: Settings,
        worker_id: str,
        *,
        stop_event: threading.Event | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store, self._email, self._settings, self._worker_id = store, email, settings, worker_id
        self._stop = stop_event or threading.Event()
        self._clock = clock

    def run(self) -> None:
        database_backoff, next_cleanup = 1.0, self._clock()
        while not self._stop.is_set():
            try:
                now = self._clock()
                if now >= next_cleanup:
                    self._store.cleanup_expired_idempotency()
                    next_cleanup = now + CLEANUP_INTERVAL
                jobs = self._store.claim(
                    self._worker_id,
                    limit=min(self._settings.worker_claim_limit, 20),
                    lease=timedelta(seconds=self._settings.worker_lease_seconds),
                )
                database_backoff = 1.0
                self._handle(jobs)
                if not jobs:
                    self._stop.wait(1.0)
            except sa.exc.OperationalError:
                self._stop.wait(database_backoff)
                database_backoff = min(database_backoff * 2, 30.0)

    def stop(self) -> None:
        self._stop.set()

    def _handle(self, jobs: Sequence[ClaimedJob]) -> None:
        for job in jobs:
            if self._stop.is_set():
                return
            result = (
                self._email.deliver(job.id, job.aggregate_id, job.payload)
                if job.job_kind == "lead_email"
                else DeliveryResult.terminal("unknown_job_kind")
            )
            self._store.record(self._worker_id, job, result)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process durable CRM notification jobs")
    parser.add_argument("--worker-id", default=f"worker-{uuid.uuid4()}")
    args = parser.parse_args(argv)
    settings = get_settings()
    factory = get_session_factory()
    worker = NotificationWorker(WorkerStore(factory), EmailAdapter(factory, settings), settings, args.worker_id)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda _signum, _frame: worker.stop())
    try:
        worker.run()
    except KeyboardInterrupt:
        worker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ClaimedJob", "NotificationWorker", "WorkerStore", "main", "retry_delay"]
