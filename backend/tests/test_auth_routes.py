from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from real_estate_crm.app import create_app
from real_estate_crm.auth.service import (
    AuthenticatedSession,
    AuthenticationRejected,
    IssuedSession,
)
from real_estate_crm.config import get_settings
from real_estate_crm.leads.routes import LeadRateLimiter
from real_estate_crm.leads.schemas import LeadAccepted

NOW = datetime(2026, 7, 31, tzinfo=timezone.utc)
USER_ID = uuid.UUID("20000000-0000-4000-8000-000000000022")


class FakeAuth:
    token = "opaque-session"
    csrf = "opaque-csrf"
    revoked = False
    role = "admin"

    def authenticate(self, email: str, password: str, _source: str) -> SimpleNamespace:
        if email != "owner@example.com" or password != "correct horse battery":
            raise AuthenticationRejected("authentication failed")
        return SimpleNamespace(id=USER_ID)

    def issue_session(self, _user_id: uuid.UUID) -> IssuedSession:
        return IssuedSession(uuid.uuid4(), self.token, self.csrf, NOW + timedelta(minutes=30), NOW + timedelta(hours=12))

    def lookup_session(self, token: str, *, refresh: bool = True) -> AuthenticatedSession | None:
        if token != self.token or self.revoked:
            return None
        return AuthenticatedSession(
            uuid.uuid4(),
            USER_ID,
            "owner@example.com",
            "CRM Owner",
            self.role,
            b"unused-by-fake",
            NOW + timedelta(minutes=30),
            NOW + timedelta(hours=12),
        )

    def verify_csrf(self, _session: AuthenticatedSession, token: str) -> bool:
        return token == self.csrf

    def revoke_session(self, token: str) -> bool:
        self.revoked = token == self.token
        return self.revoked


class FakeLead:
    def get_property(self, _slug: str) -> None:
        return None

    def accept(self, _lead: object, _key: uuid.UUID) -> tuple[LeadAccepted, bool]:
        raise AssertionError("not used")


class FakeAdmin:
    pass


def _client(auth: FakeAuth | None = None) -> tuple[TestClient, FakeAuth]:
    fake = auth or FakeAuth()
    fake.revoked = False
    fake.role = "admin"
    settings = get_settings().model_copy(
        update={"environment": "local", "public_origin": "http://testserver", "trusted_origins_raw": ""}
    )
    app = create_app(
        settings=settings,
        session_factory=sessionmaker(class_=Session),
        rate_limiter=LeadRateLimiter(),
        service_factory=lambda _sessions, _settings: FakeLead(),  # type: ignore[arg-type,return-value]
        auth_service_factory=lambda _sessions: fake,  # type: ignore[arg-type,return-value]
        admin_service_factory=lambda _sessions: FakeAdmin(),  # type: ignore[arg-type,return-value]
    )
    return TestClient(app, raise_server_exceptions=False), fake


def _login(client: TestClient, **headers: str):
    return client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "correct horse battery"},
        headers={"Origin": "http://testserver", **headers},
    )


def test_login_session_logout_cookie_and_csrf_contract() -> None:
    client, fake = _client()
    login = _login(client)
    assert login.status_code == 200
    assert login.json()["role"] == "admin"
    cookies = login.headers.get_list("set-cookie")
    assert any("session_id=" in value and "HttpOnly" in value and "SameSite=lax" in value for value in cookies)
    assert any("csrf_token=" in value and "HttpOnly" not in value and "SameSite=lax" in value for value in cookies)
    assert all("Secure" not in value for value in cookies)
    assert client.get("/api/v1/auth/session").status_code == 200

    rejected = client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "http://testserver", "X-CSRF-Token": "wrong"},
    )
    assert rejected.status_code == 403 and not fake.revoked
    logged_out = client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "http://testserver", "X-CSRF-Token": FakeAuth.csrf},
    )
    assert logged_out.status_code == 204 and fake.revoked
    assert client.get("/api/v1/auth/session").status_code == 401


def test_auth_failures_are_constant_shape_origin_bound_and_redacted() -> None:
    client, _ = _client()
    missing_origin = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "correct horse battery"},
    )
    wrong = client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "do-not-reflect-this-secret"},
        headers={"Origin": "http://testserver"},
    )
    malformed_identity = client.post(
        "/api/v1/auth/login",
        json={"email": "not-an-email", "password": "do-not-reflect-this-secret"},
        headers={"Origin": "http://testserver"},
    )
    malformed = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "x" * 129},
        headers={"Origin": "http://testserver"},
    )
    assert (missing_origin.status_code, wrong.status_code, malformed_identity.status_code, malformed.status_code) == (
        403,
        401,
        401,
        422,
    )
    assert malformed_identity.json()["error"] == wrong.json()["error"]
    assert wrong.json()["error"] == {"code": "authentication_failed", "message": "Invalid credentials"}
    assert b'crm_login_failures_total{reason="invalid_credentials"} 2.0' in client.app.state.metrics.render()
    assert "missing@example.com" not in wrong.text
    assert "do-not-reflect-this-secret" not in wrong.text
    assert "x" * 20 not in malformed.text
    for response in (missing_origin, wrong, malformed):
        assert response.headers["cache-control"] == "private, no-store"


def test_public_routes_remain_independent_and_role_dependency_fails_closed() -> None:
    client, fake = _client()
    assert client.get("/api/v1/properties/unknown").status_code == 404
    hidden = uuid.uuid4()
    assert client.get(f"/api/v1/inquiries/{hidden}").status_code == 401
    _login(client)
    fake.role = "viewer"
    assert client.get(f"/api/v1/inquiries/{hidden}").status_code == 403
