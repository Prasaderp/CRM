"""
Alembic migration environment.

Design rules:
- Online only: offline execution (without a live PostgreSQL connection) is rejected
  because PostgreSQL-specific DDL (e.g. DEFERRABLE FK, partial indexes) requires
  an active connection for autogenerate drift checking.
- All model modules are imported explicitly here so that autogenerate cannot omit tables.
- The database URL is resolved through Settings; no credential is embedded in alembic.ini.
- Migrations are never run at API or worker startup — this file is invoked explicitly.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# --- Settings must be importable before model imports ---
from real_estate_crm.config import get_settings
from real_estate_crm.db import Base

# Explicit model imports so autogenerate sees every table.
# Phase 4 models:
import real_estate_crm.leads.models  # noqa: F401
import real_estate_crm.notifications.models  # noqa: F401

# Phase 20 models:
import real_estate_crm.auth.models  # noqa: F401

# Alembic Config object — provides access to alembic.ini values.
config = context.config

# Wire Python logging from alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    settings = get_settings()
    raw = str(settings.database_url)
    # Ensure psycopg3 driver prefix.
    if raw.startswith("postgresql://") or raw.startswith("postgres://"):
        raw = "postgresql+psycopg" + raw[raw.index("://") :]
    return raw


def run_migrations_offline() -> None:
    """
    Offline mode is disabled: PostgreSQL-specific DDL cannot be safely
    generated without a live connection. Use online mode only.
    """
    print(
        "ERROR: Offline migration mode is disabled for this project. Start the database and run alembic online.",
        file=sys.stderr,
    )
    sys.exit(1)


def run_migrations_online() -> None:
    """Run migrations against the live database in a transaction."""
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # migrations use a single short-lived connection
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detect type changes and server defaults during autogenerate.
            compare_type=True,
            compare_server_default=True,
            # Include schema in migration output for correctness.
            include_schemas=False,
            # Render ANSI SQL text for non-portable constructs.
            render_as_batch=False,
            # Transaction per migration, not per statement.
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
