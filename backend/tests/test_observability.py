from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from real_estate_crm.app import create_app
from real_estate_crm.config import get_settings
from real_estate_crm.observability import Metrics, ReadinessProbe, configure_logging, request_id, safe_event


class _Service:
    def get_property(self, slug: str) -> object | None:
        if slug != "safe-home":
            return None
        return SimpleNamespace(
            slug=slug,
            title="Safe Home",
            summary="Synthetic",
            locality="Test City",
            price_label=None,
            project_registration_number=None,
            registration_authority_url=None,
        )


def _sessions(version: str = "0001_initial") -> sessionmaker[Session]:
    engine = sa.create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO alembic_version VALUES (:version)"), {"version": version})
    return sessionmaker(bind=engine)


def _app(sessions: sessionmaker[Session], *, heads: frozenset[str] = frozenset({"0001_initial"})):
    return create_app(
        settings=get_settings(),
        session_factory=sessions,
        service_factory=lambda _sessions, _settings: _Service(),  # type: ignore[arg-type,return-value]
        readiness_probe=ReadinessProbe(sessions, heads),
    )


def test_json_events_allow_only_bounded_non_pii_context() -> None:
    output = io.StringIO()
    configure_logging(stream=output)
    safe_event(
        "lead.rejected",
        request_id="safe-request-123",
        reason="validation_failed",
        inquiry_id="person@example.invalid",
        password="super-secret",
        click_id="ttclid-sensitive",
    )
    event = json.loads(output.getvalue())
    assert event["event"] == "lead.rejected" and event["level"] == "warning"
    assert event["request_id"] == "safe-request-123" and event["reason"] == "validation_failed"
    assert (
        "person@" not in output.getvalue() and "secret" not in output.getvalue() and "ttclid" not in output.getvalue()
    )
    with pytest.raises(ValueError, match="unknown"):
        safe_event("invented.event")


def test_request_ids_are_validated_and_never_echo_injection() -> None:
    supplied = "8a2f4c1e-0b6d-4f8a-9c31-77de5a10b4e2"
    assert request_id(supplied) == supplied
    # A non-UUID correlation ID cannot be stored in audit_events.request_id, so it is replaced.
    assert request_id("partner-request_123") != "partner-request_123"
    generated = request_id("person@example.invalid\r\nX-Evil: yes")
    assert generated != "person@example.invalid\r\nX-Evil: yes" and len(generated) == 36


def test_liveness_readiness_migration_drift_and_smtp_independence() -> None:
    sessions = _sessions()
    with TestClient(_app(sessions)) as client:
        assert client.get("/health/live").json() == {"status": "live"}
        ready = client.get("/health/ready")
        assert ready.status_code == 200 and ready.json() == {"status": "ready", "reason": "ready"}
    with TestClient(_app(sessions, heads=frozenset({"future_revision"}))) as client:
        drift = client.get("/health/ready")
        assert drift.status_code == 503 and drift.json()["reason"] == "migration_mismatch"


def test_database_failure_is_a_safe_readiness_failure() -> None:
    engine = sa.create_engine("sqlite+pysqlite://")
    engine.dispose()
    probe = ReadinessProbe(sessionmaker(bind=engine), frozenset({"0001_initial"}))
    ready, reason = probe()
    assert not ready and reason == "database_unavailable"


def test_metrics_and_http_logs_use_templates_not_urls_or_queries() -> None:
    output = io.StringIO()
    app = _app(_sessions())
    configure_logging(stream=output)
    with TestClient(app, client=("127.0.0.1", 50100)) as client:
        response = client.get(
            "/api/v1/properties/safe-home?email=pii@example.invalid&ttclid=secret",
            headers={"X-Request-ID": "1f0c9d3b-45ae-4a71-8f2c-6b90d1e37a55"},
        )
        missing = client.get("/unknown/pii@example.invalid?token=secret")
        metrics = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "1f0c9d3b-45ae-4a71-8f2c-6b90d1e37a55"
    assert missing.status_code == 404 and metrics.status_code == 200
    text = metrics.text
    assert 'route="/api/v1/properties/{slug}"' in text and 'route="unmatched"' in text
    assert "safe-home" not in text and "pii@example" not in text and "ttclid" not in text
    logs = output.getvalue()
    assert "/api/v1/properties/{slug}" in logs and "pii@example" not in logs and "secret" not in logs


def test_metrics_are_loopback_only_and_labels_fail_closed() -> None:
    metrics = Metrics.create()
    metrics.observe_request("/attacker-controlled", "TRACE", 799, -100)
    with pytest.raises(ValueError, match="unbounded"):
        metrics.observe_lead("property-123")
    with pytest.raises(ValueError, match="unbounded"):
        metrics.observe_login_failure("person@example.invalid")
    rendered = metrics.render().decode()
    assert 'method="OTHER",route="unmatched",status_class="5xx"' in rendered
    with TestClient(_app(_sessions()), client=("203.0.113.10", 50100)) as client:
        response = client.get("/metrics")
    assert response.status_code == 404 and "crm_http" not in response.text
