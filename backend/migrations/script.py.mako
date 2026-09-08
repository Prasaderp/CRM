"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Lock/backfill implications:
    - (State any table locks, backfill jobs, or advisory locks this migration requires.)
    - Initial schema (0001): transactional, runs on an empty database.
    - Additive changes: default to nullable-first; avoid full-table rewrites in production.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    # WARNING: downgrade is permitted only in local/test environments.
    # Never run destructive downgrade against production data without explicit sign-off.
    ${downgrades if downgrades else "pass"}
