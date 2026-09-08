from __future__ import annotations

import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
import sqlalchemy as sa
from argon2 import extract_parameters
from sqlalchemy.orm import Session, sessionmaker

from real_estate_crm.auth.models import AuditEvent, Session as AuthSession
from real_estate_crm.auth.models import User, audit_context
from real_estate_crm.auth.service import (
    AuthenticatedSession,
    AuthenticationRejected,
    AuthorizationRejected,
    AuthService,
    DuplicateUser,
    LoginThrottle,
    PASSWORD_HASHER,
    PasswordPolicyError,
    hash_password,
    validate_password,
    verify_password,
)
from real_estate_crm.config import get_settings

NOW = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
PASSWORD = "correct horse battery"


class MutableClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def auth(db_session: Session) -> tuple[AuthService, sessionmaker[Session], MutableClock]:
    factory = sessionmaker(bind=db_session.connection(), expire_on_commit=False)
    clock = MutableClock()
    return AuthService(factory, clock=clock), factory, clock


def _user(service: AuthService, *, email: str | None = None, role: str = "admin") -> User:
    return service.create_user(email or f"user-{uuid.uuid4().hex}@example.com", "Test User", PASSWORD, role)


def test_password_policy_argon2id_and_benchmark() -> None:
    for value in ("x" * 7, "x" * 129):
        with pytest.raises(PasswordPolicyError):
            validate_password(value)
    validate_password("😀" * 128)
    valid = "😀" * 8
    encoded = hash_password(valid)
    params = extract_parameters(encoded)
    assert params.type.name == "ID"
    assert (params.memory_cost, params.time_cost, params.parallelism, params.salt_len, params.hash_len) == (
        65_536,
        3,
        1,
        16,
        32,
    )
    assert verify_password(encoded, valid)
    assert not verify_password(encoded, "wrong password value")

    durations = []
    for index in range(10):
        started = time.perf_counter()
        PASSWORD_HASHER.hash(f"benchmark-password-{index}")
        durations.append(time.perf_counter() - started)
    p95 = statistics.quantiles(durations, n=20)[18]
    assert p95 <= 0.5, f"Argon2id p95 {p95:.3f}s exceeds the architecture budget"


def test_user_creation_normalizes_identity_and_is_transactionally_unique(
    db_session: Session, auth: tuple[AuthService, sessionmaker[Session], MutableClock]
) -> None:
    service, factory, _ = auth
    created = service.create_user("  Owner@Example.COM ", "  First   Admin ", PASSWORD, "admin")
    assert created.normalized_email == "owner@example.com" and created.display_name == "First Admin"
    assert created.password_hash != PASSWORD and verify_password(created.password_hash, PASSWORD)
    with pytest.raises(DuplicateUser):
        service.create_user("owner@example.com", "Duplicate", PASSWORD, "agent")
    assert db_session.scalar(sa.select(sa.func.count()).select_from(User)) == 1
    for role in ("owner", "", "ADMIN"):
        with pytest.raises(ValueError):
            service.create_user(f"{role or 'blank'}@example.com", "Invalid", PASSWORD, role)


def test_authentication_has_generic_dummy_failure_and_throttles_account_and_source(
    auth: tuple[AuthService, sessionmaker[Session], MutableClock],
) -> None:
    service, factory, _ = auth
    user = _user(service, email="known@example.com")
    assert service.authenticate("KNOWN@example.com", PASSWORD, "127.0.0.1").id == user.id
    messages = set()
    for email in ("missing@example.com", "not-an-email", "known@example.com"):
        with pytest.raises(AuthenticationRejected) as rejected:
            service.authenticate(email, "incorrect-password", "127.0.0.2")
        messages.add(str(rejected.value))
    assert messages == {"authentication failed"}

    for _ in range(5):
        with pytest.raises(AuthenticationRejected):
            service.authenticate("known@example.com", "incorrect-password", "127.0.0.3")
    with pytest.raises(AuthenticationRejected):
        service.authenticate("known@example.com", PASSWORD, "127.0.0.4")

    monotonic = [0.0]
    throttle = LoginThrottle(clock=lambda: monotonic[0])
    source_service = AuthService(factory, throttle=throttle)
    for index in range(20):
        with pytest.raises(AuthenticationRejected):
            source_service.authenticate(f"unknown-{index}@example.com", "incorrect-password", "198.51.100.1")
    with pytest.raises(AuthenticationRejected):
        source_service.authenticate("known@example.com", PASSWORD, "198.51.100.1")
    monotonic[0] += 901
    assert source_service.authenticate("known@example.com", PASSWORD, "198.51.100.1").id == user.id


def test_issue_lookup_refresh_csrf_expiry_revocation_and_roles(
    db_session: Session, auth: tuple[AuthService, sessionmaker[Session], MutableClock]
) -> None:
    service, _, clock = auth
    user = _user(service, role="agent")
    issued = service.issue_session(user.id)
    stored = db_session.get(AuthSession, issued.session_id)
    assert stored and len(stored.token_sha256) == len(stored.csrf_sha256) == 32
    assert issued.token.encode() not in stored.token_sha256 and issued.csrf_token.encode() not in stored.csrf_sha256

    current = service.lookup_session(issued.token)
    assert current and current.user_id == user.id and current.role == "agent"
    assert service.verify_csrf(current, issued.csrf_token)
    assert not service.verify_csrf(current, f"{issued.csrf_token}x")
    service.require_role(current, {"admin", "agent"})
    with pytest.raises(AuthorizationRejected):
        service.require_role(current, {"admin"})

    clock.value += timedelta(minutes=4, seconds=59)
    assert service.lookup_session(issued.token)
    db_session.refresh(stored)
    assert stored.last_seen_at == NOW
    clock.value += timedelta(seconds=1)
    refreshed = service.lookup_session(issued.token)
    db_session.refresh(stored)
    assert refreshed and stored.last_seen_at == clock.value
    assert stored.idle_expires_at == clock.value + timedelta(minutes=30)

    assert service.revoke_session(issued.token)
    assert not service.revoke_session(issued.token)
    assert service.lookup_session(issued.token) is None


@pytest.mark.parametrize("expiry", ["idle", "absolute"])
def test_expired_sessions_fail_without_refresh(
    db_session: Session,
    auth: tuple[AuthService, sessionmaker[Session], MutableClock],
    expiry: str,
) -> None:
    service, _, clock = auth
    issued = service.issue_session(_user(service).id)
    clock.value = issued.idle_expires_at if expiry == "idle" else issued.absolute_expires_at
    assert service.lookup_session(issued.token) is None
    stored = db_session.get(AuthSession, issued.session_id)
    assert stored and stored.last_seen_at == NOW


def test_inactive_user_and_malformed_tokens_fail_closed(
    db_session: Session, auth: tuple[AuthService, sessionmaker[Session], MutableClock]
) -> None:
    service, _, _ = auth
    user = _user(service)
    issued = service.issue_session(user.id)
    user_row = db_session.get(User, user.id)
    assert user_row
    user_row.is_active = False
    db_session.flush()
    assert service.lookup_session(issued.token) is None
    assert service.lookup_session("") is None
    assert service.lookup_session("x" * 1_000) is None


def test_audit_context_rejects_sensitive_or_unbounded_values() -> None:
    assert dict(audit_context({"from_status": "new", "to_status": "contacted"}))["to_status"] == "contacted"
    with pytest.raises(ValueError):
        audit_context({"email": "pii@example.com"})
    with pytest.raises(ValueError):
        audit_context({"reason_code": "x" * 121})
    with pytest.raises(ValueError):
        AuditEvent(
            id=uuid.uuid4(),
            actor_user_id=None,
            action="inquiry.changed",
            entity_type="inquiry",
            entity_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
            context={"email": "pii@example.com"},
        )


def test_concurrent_lookup_and_logout_are_race_safe(test_engine: sa.Engine) -> None:
    identity = f"race-{uuid.uuid4().hex}@example.com"
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    service = AuthService(factory)
    user = _user(service, email=identity)
    issued = service.issue_session(user.id)
    barrier = Barrier(8)

    def operation(index: int) -> AuthenticatedSession | bool | None:
        barrier.wait(timeout=5)
        return service.revoke_session(issued.token) if index == 0 else service.lookup_session(issued.token)

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = [future.result(timeout=10) for future in [pool.submit(operation, i) for i in range(8)]]
        assert results[0] is True
        assert service.lookup_session(issued.token) is None
        with Session(test_engine) as session:
            row = session.get(AuthSession, issued.session_id)
            assert row and row.revoked_at is not None
    finally:
        with test_engine.begin() as connection:
            connection.execute(sa.delete(User).where(User.id == user.id))


def _target_database() -> str:
    return (get_settings().database_url.path or "").lstrip("/")


def test_create_user_has_no_password_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import create_user

    monkeypatch.setattr(
        create_user.getpass,
        "getpass",
        lambda _prompt: pytest.fail("password must never be accepted on the command line"),
    )
    with pytest.raises(SystemExit):
        create_user.main(["owner@example.com", "Owner", "admin", "password-on-cli"])


def test_create_user_refuses_when_database_name_not_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import create_user

    monkeypatch.setattr(create_user, "get_settings", get_settings)
    monkeypatch.setattr("builtins.input", lambda _prompt: "not-the-database")
    monkeypatch.setattr(
        create_user.getpass,
        "getpass",
        lambda _prompt: pytest.fail("password prompt must not run before confirmation"),
    )
    with pytest.raises(SystemExit) as rejected:
        create_user.main(["owner@example.com", "Owner", "admin"])
    assert rejected.value.code == 2


def test_create_user_prompts_twice_and_delegates_one_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import create_user

    prompts = iter([PASSWORD, PASSWORD])
    calls: list[tuple[str, str, str, str]] = []

    class FakeAuth:
        def __init__(self, _factory: object) -> None:
            pass

        def create_user(self, email: str, name: str, password: str, role: str) -> User:
            calls.append((email, name, password, role))
            return User(
                id=uuid.UUID("20000000-0000-4000-8000-000000000021"),
                normalized_email=email,
                display_name=name,
                password_hash="<not-printed>",
                role=role,
            )

    monkeypatch.setattr(create_user, "get_settings", get_settings)
    monkeypatch.setattr(create_user, "get_session_factory", lambda: object())
    monkeypatch.setattr(create_user, "AuthService", FakeAuth)
    monkeypatch.setattr("builtins.input", lambda _prompt: _target_database())
    monkeypatch.setattr(create_user.getpass, "getpass", lambda _prompt: next(prompts))
    assert create_user.main(["owner@example.com", "Owner", "admin"]) == 0
    assert calls == [("owner@example.com", "Owner", PASSWORD, "admin")]


def test_create_user_rejects_mismatched_password_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import create_user

    prompts = iter([PASSWORD, PASSWORD + "-different"])
    monkeypatch.setattr(create_user, "get_settings", get_settings)
    monkeypatch.setattr(create_user, "AuthService", lambda _f: pytest.fail("must not create a user"))
    monkeypatch.setattr("builtins.input", lambda _prompt: _target_database())
    monkeypatch.setattr(create_user.getpass, "getpass", lambda _prompt: next(prompts))
    with pytest.raises(SystemExit) as rejected:
        create_user.main(["owner@example.com", "Owner", "admin"])
    assert rejected.value.code == 2
