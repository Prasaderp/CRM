from __future__ import annotations

import ipaddress
import json
import logging
import re
import sys
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TextIO

import sqlalchemy as sa
import structlog
from alembic.config import Config
from alembic.script import ScriptDirectory
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from sqlalchemy.orm import Session, sessionmaker

EventLevel = Literal["debug", "info", "warning", "error"]
_EVENT_LEVELS: Final[dict[str, EventLevel]] = {
    "http.request.completed": "info",
    "lead.accepted": "info",
    "lead.idempotent_replay": "info",
    "lead.rejected": "warning",
    "outbox.claimed": "debug",
    "email.sent": "info",
    "email.retry_scheduled": "warning",
    "email.dead": "error",
    "auth.login.failed": "warning",
    "admin.inquiry.changed": "info",
}
_SAFE_KEYS: Final = frozenset(
    {
        "request_id",
        "route",
        "method",
        "status",
        "duration_ms",
        "inquiry_id",
        "property_id",
        "source",
        "surface",
        "reason",
        "job_id",
        "worker_id",
        "attempt",
        "next_due_at",
        "actor_id",
        "action",
        "old_status",
        "new_status",
    }
)
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+ -]{0,127}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,63}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
_ROUTES: Final = frozenset(
    {
        "/api/v1/leads",
        "/api/v1/properties/{slug}",
        "/api/v1/auth/login",
        "/api/v1/auth/session",
        "/api/v1/auth/logout",
        "/api/v1/inquiries",
        "/api/v1/inquiries/{inquiry_id}",
        "/api/v1/inquiries/{inquiry_id}/status",
        "/api/v1/inquiries/{inquiry_id}/assignment",
        "/api/v1/users",
        "/health/live",
        "/health/ready",
        "/metrics",
        "/openapi.json",
        "/docs",
        "/redoc",
        "unmatched",
    }
)
_METHODS: Final = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "OTHER"})
_STATUS_CLASSES: Final = frozenset({"1xx", "2xx", "3xx", "4xx", "5xx"})
_LEAD_OUTCOMES: Final = frozenset({"accepted", "replay", "rejected", "conflict"})
_EMAIL_OUTCOMES: Final = frozenset({"sent", "retry", "dead"})
_LOGIN_FAILURES: Final = frozenset({"invalid_credentials", "throttled"})
_BOUNDED_CONTEXT: Final[dict[str, frozenset[str]]] = {
    "source": frozenset({"website", "meta", "tiktok", "x", "direct", "unknown"}),
    "surface": frozenset({"website", "native", "admin", "api"}),
    "reason": frozenset(
        {
            "validation_failed",
            "malformed_json",
            "unsupported_media_type",
            "body_too_large",
            "invalid_idempotency_key",
            "rate_limited",
            "idempotency_conflict",
            "property_not_found",
            "service_unavailable",
            "internal_error",
            "invalid_credentials",
            "throttled",
            "token_expired",
            "smtp_timeout",
            "smtp_temporary",
            "smtp_permanent",
            "delivery_limits_exceeded",
            "unknown_job_kind",
        }
    ),
    "action": frozenset({"status", "assignment", "note"}),
    "old_status": frozenset({"new", "contacted", "qualified", "viewing", "won", "lost", "closed"}),
    "new_status": frozenset({"new", "contacted", "qualified", "viewing", "won", "lost", "closed"}),
}
_LATENCY_BUCKETS: Final = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0)


def configure_logging(*, stream: TextIO = sys.stdout) -> None:
    structlog.configure(
        processors=(
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(serializer=json.dumps),
        ),
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        logger_factory=structlog.PrintLoggerFactory(file=stream),
        cache_logger_on_first_use=False,
    )


def safe_event(event: str, **context: object) -> None:
    level = _EVENT_LEVELS.get(event)
    if level is None:
        raise ValueError("unknown operational event")
    safe = {key: value for key, value in context.items() if key in _SAFE_KEYS and _safe_context_value(key, value)}
    getattr(structlog.get_logger("real_estate_crm"), level)(event, **safe)


def request_id(value: str | None) -> str:
    """Correlation ID for one request.

    A caller-supplied value is honoured only when it is a UUID: `audit_events.request_id`
    is a `uuid NOT NULL` column, so any other shape would fail the audited mutation.
    """
    return value if value is not None and _UUID.fullmatch(value) else str(uuid.uuid4())


def is_loopback(host: str | None) -> bool:
    try:
        return host is not None and ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def route_template(scope: Mapping[str, object]) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path in _ROUTES else "unmatched"


def _safe_context_value(key: str, value: object) -> bool:
    if key == "route":
        return isinstance(value, str) and value in _ROUTES
    if key == "method":
        return isinstance(value, str) and value in _METHODS
    if key == "request_id":
        return isinstance(value, str) and _REQUEST_ID.fullmatch(value) is not None
    if key in {"inquiry_id", "property_id", "job_id", "actor_id"}:
        return isinstance(value, str) and _UUID.fullmatch(value) is not None
    if key in _BOUNDED_CONTEXT:
        return isinstance(value, str) and value in _BOUNDED_CONTEXT[key]
    if isinstance(value, bool) or value is None:
        return True
    if isinstance(value, (int, float)):
        return 0 <= value <= 10**12
    return isinstance(value, str) and _SAFE_VALUE.fullmatch(value) is not None and "@" not in value


@dataclass(slots=True)
class Metrics:
    registry: CollectorRegistry
    requests: Counter
    request_latency: Histogram
    leads: Counter
    outbox_jobs: Gauge
    outbox_oldest_seconds: Gauge
    email: Counter
    email_latency: Histogram
    login_failures: Counter
    stale_version_conflicts: Counter

    @classmethod
    def create(cls) -> Metrics:
        registry = CollectorRegistry(auto_describe=True)
        return cls(
            registry,
            Counter("crm_http_requests_total", "HTTP requests", ("route", "method", "status_class"), registry=registry),
            Histogram("crm_http_request_duration_seconds", "HTTP latency", ("route", "method"), buckets=_LATENCY_BUCKETS, registry=registry),
            Counter("crm_leads_total", "Lead acceptance outcomes", ("outcome",), registry=registry),
            Gauge("crm_outbox_jobs", "Outbox jobs by state", ("state",), registry=registry),
            Gauge("crm_outbox_oldest_pending_seconds", "Age of oldest pending outbox job", registry=registry),
            Counter("crm_email_total", "Email delivery outcomes", ("outcome",), registry=registry),
            Histogram("crm_email_duration_seconds", "Email delivery latency", ("outcome",), buckets=_LATENCY_BUCKETS, registry=registry),
            Counter("crm_login_failures_total", "Login failures", ("reason",), registry=registry),
            Counter("crm_stale_version_conflicts_total", "Optimistic concurrency conflicts", registry=registry),
        )

    def observe_request(self, route: str, method: str, status: int, duration_seconds: float) -> None:
        bounded_route = route if route in _ROUTES else "unmatched"
        bounded_method = method if method in _METHODS else "OTHER"
        status_class = f"{min(5, max(1, status // 100))}xx"
        if status_class not in _STATUS_CLASSES:
            status_class = "5xx"
        self.requests.labels(bounded_route, bounded_method, status_class).inc()
        self.request_latency.labels(bounded_route, bounded_method).observe(max(0.0, duration_seconds))

    def observe_lead(self, outcome: str) -> None:
        if outcome not in _LEAD_OUTCOMES:
            raise ValueError("unbounded lead outcome")
        self.leads.labels(outcome).inc()

    def observe_login_failure(self, reason: str) -> None:
        if reason not in _LOGIN_FAILURES:
            raise ValueError("unbounded login failure reason")
        self.login_failures.labels(reason).inc()

    def observe_stale_version(self) -> None:
        self.stale_version_conflicts.inc()

    def render(self) -> bytes:
        return generate_latest(self.registry)


class ReadinessProbe:
    def __init__(self, sessions: sessionmaker[Session], expected_heads: frozenset[str]) -> None:
        if not expected_heads:
            raise ValueError("at least one Alembic head is required")
        self._sessions, self._expected_heads = sessions, expected_heads

    def __call__(self) -> tuple[bool, str]:
        try:
            with self._sessions() as session:
                session.execute(sa.text("SELECT 1"))
                current = frozenset(session.scalars(sa.text("SELECT version_num FROM alembic_version")))
        except sa.exc.SQLAlchemyError:
            return False, "database_unavailable"
        return (True, "ready") if current == self._expected_heads else (False, "migration_mismatch")


def alembic_heads(ini_path: Path | None = None) -> frozenset[str]:
    backend = Path(__file__).resolve().parents[2]
    config = Config(str(ini_path or backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


def monotonic_seconds() -> float:
    return time.monotonic()


__all__ = [
    "Metrics",
    "ReadinessProbe",
    "alembic_heads",
    "configure_logging",
    "is_loopback",
    "monotonic_seconds",
    "request_id",
    "route_template",
    "safe_event",
]
