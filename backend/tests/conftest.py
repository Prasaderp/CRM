from __future__ import annotations

import os

# Provide settings defaults before any Settings-dependent import fires.
# These must be set before any `from real_estate_crm.*` import at module level.
os.environ.setdefault("TEST_DATABASE_URL", "postgresql://postgres:postgrespassword@127.0.0.1:5433/real_estate_crm_test")
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgrespassword@127.0.0.1:5433/real_estate_crm_test"),
)
os.environ.setdefault("PUBLIC_ORIGIN", "http://localhost:5173")
os.environ.setdefault("CANONICAL_NOTICE_VERSION", "2026-07-30")
os.environ.setdefault("CANONICAL_NOTICE_TEXT", "By submitting this form, you agree to our privacy policy.")
os.environ.setdefault("SMTP_HOST", "127.0.0.1")
os.environ.setdefault("SMTP_PORT", "1025")
os.environ.setdefault("SMTP_SENDER", "test@leads.client.example")
os.environ.setdefault("RECIPIENT_ALLOW_LIST", "agent@leads.client.example")

import uuid
from datetime import datetime, timezone
from typing import Generator

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

# ── Guard: refuse to run against any non-test URL ────────────────────────────

_TEST_DB_URL: str = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:postgrespassword@127.0.0.1:5433/real_estate_crm_test"
)
_SAFE_NAMES = {"real_estate_crm_test", "crm_test"}


def _assert_test_url(url: str) -> None:
    """Raise immediately if the URL does not look like the test database."""
    if not url:
        pytest.exit(
            "TEST_DATABASE_URL is not set. Set it to the explicit test database URL before running integration tests.",
            returncode=2,
        )
    # Extract the database name from the URL path segment.
    db_name = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    if db_name not in _SAFE_NAMES:
        pytest.exit(
            f"TEST_DATABASE_URL points to '{db_name}', which is not an allowed test "
            f"database name (allowed: {sorted(_SAFE_NAMES)}). "
            "Refusing to run destructive test setup.",
            returncode=2,
        )


from _testutils import alembic_cfg as _alembic_cfg, psycopg_url as _psycopg_url  # noqa: E402


# ── Session-scoped engine ─────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def test_db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", "")
    _assert_test_url(url)
    return url


@pytest.fixture(scope="session")
def test_engine(test_db_url: str) -> Generator[sa.Engine, None, None]:
    engine = create_engine(
        _psycopg_url(test_db_url),
        pool_pre_ping=True,
        pool_size=5,
        future=True,
    )
    yield engine
    engine.dispose()


# ── Schema lifecycle: upgrade once per session, downgrade at teardown ─────────


@pytest.fixture(scope="session", autouse=True)
def apply_migrations(test_db_url: str, test_engine: sa.Engine) -> Generator[None, None, None]:
    """Upgrade to head before the test session; downgrade to base after."""
    cfg = _alembic_cfg(test_db_url)

    # use a temporary env-var override so env.py reads the test URL from settings
    # if it happens to be invoked (our override via set_main_option takes priority).
    old_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_db_url

    # Bust the lru_cache on get_settings() so the test URL is picked up.
    try:
        from real_estate_crm.config import get_settings

        get_settings.cache_clear()
    except Exception:
        pass

    try:
        alembic_command.upgrade(cfg, "head")
        yield
        alembic_command.downgrade(cfg, "base")
    finally:
        if old_db_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_db_url
        # Re-clear so subsequent get_settings() calls reflect restored state.
        try:
            from real_estate_crm.config import get_settings

            get_settings.cache_clear()
        except Exception:
            pass


# ── Per-test isolated session (wraps every test in a SAVEPOINT rollback) ─────


@pytest.fixture
def db_session(test_engine: sa.Engine) -> Generator[Session, None, None]:
    """
    Yield a Session whose writes are rolled back after each test.

    Uses nested transactions (SAVEPOINT) so the schema stays intact but data is clean.
    """
    connection = test_engine.connect()
    trans = connection.begin()
    # SQLAlchemy 2.x: pass connection directly, not via bind= kwarg
    session = Session(connection, autocommit=False, autoflush=False)

    # Begin a SAVEPOINT so the test body can itself commit/rollback without
    # affecting the outer transaction that we'll roll back in teardown.
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(session: Session, transaction: sa.orm.SessionTransaction) -> None:  # type: ignore[override]
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()


# ── Deterministic seams ───────────────────────────────────────────────────────


@pytest.fixture
def fixed_uuid() -> uuid.UUID:
    return uuid.UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 7, 31, 0, 0, 0, tzinfo=timezone.utc)


# ── Synthetic factory re-exports for convenience ─────────────────────────────
# Full implementations live in factories.py (importable by any test module).
from factories import make_contact, make_inquiry, make_property  # noqa: E402, F401
