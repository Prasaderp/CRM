from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from real_estate_crm.config import get_settings


class DatabaseError(Exception):
    """Wraps SQLAlchemy OperationalError / connectivity failures."""


class Base(DeclarativeBase):
    """Shared declarative base — all ORM models inherit from this."""


def _build_engine() -> sa.Engine:
    cfg = get_settings()
    url = str(cfg.database_url)
    # psycopg3 driver: replace postgresql:// with postgresql+psycopg://
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        url = "postgresql+psycopg" + url[url.index("://") :]
    return sa.create_engine(
        url,
        pool_pre_ping=True,  # validate connection before use
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        connect_args={"connect_timeout": 10},
        future=True,
    )


# Module-level singletons — instantiated once per worker/API process.
_engine: sa.Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def get_engine() -> sa.Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _SessionFactory


@contextmanager
def db_session() -> Generator[Session, None, None]:
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except sa.exc.OperationalError as exc:
        session.rollback()
        raise DatabaseError(str(exc)) from exc
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def probe_connectivity() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except sa.exc.SQLAlchemyError as exc:
        raise DatabaseError(f"Database connectivity probe failed: {exc}") from exc
