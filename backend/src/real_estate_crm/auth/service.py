from __future__ import annotations

import hashlib
import hmac
import base64
import secrets
import threading
import time
import unicodedata
import uuid
from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import joinedload, sessionmaker
from typing import Any, cast

from real_estate_crm.auth.models import Session, User
from real_estate_crm.leads.normalization import normalize_email

PASSWORD_MIN_CHARACTERS = 8
PASSWORD_MAX_CHARACTERS = 128
PASSWORD_MAX_BYTES = 512
SESSION_ABSOLUTE_LIFETIME = timedelta(hours=12)
SESSION_IDLE_LIFETIME = timedelta(minutes=30)
SESSION_REFRESH_INTERVAL = timedelta(minutes=5)
LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_COOLDOWN = timedelta(minutes=15)
ACCOUNT_FAILURE_LIMIT = 5
SOURCE_FAILURE_LIMIT = 20
ROLES = frozenset({"admin", "agent"})

PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
_DUMMY_HASH = PASSWORD_HASHER.hash("constant-work-dummy-password")


class AuthenticationRejected(Exception):
    """Constant-shape authentication failure."""


class PasswordPolicyError(ValueError):
    pass


class DuplicateUser(ValueError):
    pass


class InactiveUser(ValueError):
    pass


class AuthorizationRejected(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class IssuedSession:
    session_id: uuid.UUID
    token: str
    csrf_token: str
    idle_expires_at: datetime
    absolute_expires_at: datetime


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    session_id: uuid.UUID
    user_id: uuid.UUID
    normalized_email: str
    display_name: str
    role: str
    csrf_sha256: bytes
    idle_expires_at: datetime
    absolute_expires_at: datetime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def validate_password(password: str) -> None:
    if not isinstance(password, str):
        raise PasswordPolicyError("password must be a string")
    characters, encoded = len(password), password.encode("utf-8")
    if not PASSWORD_MIN_CHARACTERS <= characters <= PASSWORD_MAX_CHARACTERS or len(encoded) > PASSWORD_MAX_BYTES:
        raise PasswordPolicyError(
            f"password must contain {PASSWORD_MIN_CHARACTERS}-{PASSWORD_MAX_CHARACTERS} Unicode characters "
            f"and at most {PASSWORD_MAX_BYTES} UTF-8 bytes"
        )


def hash_password(password: str) -> str:
    validate_password(password)
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (VerificationError, InvalidHashError, TypeError):
        return False


def normalize_identity(email: str) -> str:
    if not isinstance(email, str):
        raise ValueError("email is required")
    normalized = normalize_email(email.strip())
    if normalized is None:
        raise ValueError("email is required")
    return normalized.casefold()


def _sha256(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


class LoginThrottle:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._account: dict[str, deque[float]] = defaultdict(deque)
        self._source: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def blocked(self, account: str, source: str) -> bool:
        now = self._clock()
        with self._lock:
            account_events = self._prune(self._account, account, now)
            source_events = self._prune(self._source, source, now)
            return self._limited(account_events, ACCOUNT_FAILURE_LIMIT, now) or self._limited(
                source_events, SOURCE_FAILURE_LIMIT, now
            )

    def failure(self, account: str, source: str) -> None:
        now = self._clock()
        with self._lock:
            self._prune(self._account, account, now).append(now)
            self._prune(self._source, source, now).append(now)

    def success(self, account: str) -> None:
        with self._lock:
            self._account.pop(account, None)

    @staticmethod
    def _limited(events: deque[float], limit: int, now: float) -> bool:
        return len(events) >= limit and now - events[-1] < LOGIN_COOLDOWN.total_seconds()

    @staticmethod
    def _prune(store: dict[str, deque[float]], key: str, now: float) -> deque[float]:
        events = store[key]
        cutoff = now - LOGIN_WINDOW.total_seconds()
        while events and events[0] <= cutoff:
            events.popleft()
        if not events:
            store.pop(key, None)
            events = store[key]
        return events


class AuthService:
    def __init__(
        self,
        session_factory: sessionmaker[OrmSession],
        *,
        clock: Callable[[], datetime] = utc_now,
        token_bytes: Callable[[int], bytes] = secrets.token_bytes,
        throttle: LoginThrottle | None = None,
        refresh_interval: timedelta = SESSION_REFRESH_INTERVAL,
    ) -> None:
        if refresh_interval < SESSION_REFRESH_INTERVAL:
            raise ValueError("session refresh interval cannot be below five minutes")
        self._sessions = session_factory
        self._clock = clock
        self._token_bytes = token_bytes
        self._throttle = throttle or LoginThrottle()
        self._refresh_interval = refresh_interval

    def authenticate(self, email: str, password: str, source_ip: str) -> User:
        try:
            identity = normalize_identity(email)
        except (TypeError, ValueError):
            identity = "<invalid>"
        safe_password = (
            password
            if isinstance(password, str)
            and len(password) <= PASSWORD_MAX_CHARACTERS
            and len(password.encode("utf-8")) <= PASSWORD_MAX_BYTES
            else "constant-work-invalid-password"
        )
        with self._sessions() as session:
            user = session.scalar(sa.select(User).where(User.normalized_email == identity))
            candidate_hash = user.password_hash if user is not None and user.is_active else _DUMMY_HASH
            verified = verify_password(candidate_hash, safe_password)
            blocked = self._throttle.blocked(identity, source_ip)
            if blocked or user is None or not user.is_active or not verified:
                self._throttle.failure(identity, source_ip)
                raise AuthenticationRejected("authentication failed")
            self._throttle.success(identity)
            session.expunge(user)
            return user

    def create_user(self, email: str, display_name: str, password: str, role: str) -> User:
        identity = normalize_identity(email)
        name = unicodedata.normalize("NFC", " ".join(display_name.split()))
        if not 1 <= len(name) <= 120:
            raise ValueError("display name must contain 1-120 characters")
        if role not in ROLES:
            raise ValueError("role must be admin or agent")
        user = User(
            id=uuid.uuid4(),
            normalized_email=identity,
            display_name=name,
            password_hash=hash_password(password),
            role=role,
        )
        try:
            with self._sessions() as session, session.begin():
                session.add(user)
                session.flush()
                session.expunge(user)
        except sa.exc.IntegrityError as exc:
            raise DuplicateUser("user identity already exists") from exc
        return user

    def issue_session(self, user_id: uuid.UUID) -> IssuedSession:
        now = self._aware_now()
        absolute = now + SESSION_ABSOLUTE_LIFETIME
        token, csrf_token = self._opaque_token(), self._opaque_token()
        row = Session(
            id=uuid.uuid4(),
            user_id=user_id,
            token_sha256=_sha256(token),
            csrf_sha256=_sha256(csrf_token),
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + SESSION_IDLE_LIFETIME,
            absolute_expires_at=absolute,
        )
        with self._sessions() as session, session.begin():
            active = session.scalar(sa.select(User.is_active).where(User.id == user_id).with_for_update())
            if active is not True:
                raise InactiveUser("cannot issue a session for an inactive or missing user")
            session.add(row)
        return IssuedSession(row.id, token, csrf_token, row.idle_expires_at, absolute)

    def lookup_session(self, token: str, *, refresh: bool = True) -> AuthenticatedSession | None:
        if not isinstance(token, str) or not token or len(token) > 256:
            return None
        now, token_hash = self._aware_now(), _sha256(token)
        with self._sessions() as session, session.begin():
            row = session.scalar(
                sa.select(Session)
                .options(joinedload(Session.user, innerjoin=True))
                .where(Session.token_sha256 == token_hash)
                .with_for_update(of=Session)
            )
            if (
                row is None
                or row.revoked_at is not None
                or not row.user.is_active
                or now >= row.idle_expires_at
                or now >= row.absolute_expires_at
            ):
                return None
            if refresh and now - row.last_seen_at >= self._refresh_interval:
                row.last_seen_at = now
                row.idle_expires_at = min(now + SESSION_IDLE_LIFETIME, row.absolute_expires_at)
            return AuthenticatedSession(
                row.id,
                row.user.id,
                row.user.normalized_email,
                row.user.display_name,
                row.user.role,
                row.csrf_sha256,
                row.idle_expires_at,
                row.absolute_expires_at,
            )

    def revoke_session(self, token: str) -> bool:
        if not isinstance(token, str) or not token or len(token) > 256:
            return False
        now = self._aware_now()
        with self._sessions() as session, session.begin():
            changed = cast(CursorResult[Any], session.execute(
                sa.update(Session)
                .where(Session.token_sha256 == _sha256(token), Session.revoked_at.is_(None))
                .values(revoked_at=now)
            )).rowcount
        return changed == 1

    @staticmethod
    def verify_csrf(session: AuthenticatedSession, csrf_token: str) -> bool:
        return isinstance(csrf_token, str) and 0 < len(csrf_token) <= 256 and hmac.compare_digest(
            session.csrf_sha256, _sha256(csrf_token)
        )

    @staticmethod
    def require_role(session: AuthenticatedSession, allowed: Iterable[str]) -> None:
        accepted = frozenset(allowed)
        if not accepted or not accepted <= ROLES or session.role not in accepted:
            raise AuthorizationRejected("insufficient role")

    def _opaque_token(self) -> str:
        raw = self._token_bytes(32)
        if len(raw) != 32:
            raise ValueError("token generator must return exactly 32 bytes")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now


__all__ = [
    "ACCOUNT_FAILURE_LIMIT",
    "AuthenticatedSession",
    "AuthenticationRejected",
    "AuthorizationRejected",
    "AuthService",
    "DuplicateUser",
    "IssuedSession",
    "LoginThrottle",
    "PASSWORD_HASHER",
    "PasswordPolicyError",
    "ROLES",
    "SOURCE_FAILURE_LIMIT",
    "hash_password",
    "normalize_identity",
    "validate_password",
    "verify_password",
]
