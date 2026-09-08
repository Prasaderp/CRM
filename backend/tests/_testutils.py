from __future__ import annotations

import os

from alembic.config import Config as AlembicConfig


def psycopg_url(url: str) -> str:
    """Convert postgresql:// → postgresql+psycopg:// for SQLAlchemy 2 / psycopg3."""
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        return "postgresql+psycopg" + url[url.index("://") :]
    return url


def alembic_cfg(url: str) -> AlembicConfig:
    """Return an AlembicConfig wired to the given URL (not the dev URL from settings)."""
    ini_path = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
    cfg = AlembicConfig(os.path.normpath(ini_path))
    # Make sure alembic finds the migrations folder when tests are run from the project root
    cfg.set_main_option(
        "script_location", os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "migrations"))
    )
    cfg.set_main_option("sqlalchemy.url", psycopg_url(url))
    return cfg
