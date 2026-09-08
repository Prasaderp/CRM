from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("normalized_email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("normalized_email", name="users_normalized_email_key"),
        sa.CheckConstraint("char_length(normalized_email) <= 254", name="users_email_len_ck"),
        sa.CheckConstraint("char_length(display_name) BETWEEN 1 AND 120", name="users_name_len_ck"),
        sa.CheckConstraint("role IN ('admin','agent')", name="users_role_ck"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", name="sessions_user_id_fkey", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("csrf_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_sha256", name="sessions_token_sha256_key"),
        sa.CheckConstraint("octet_length(token_sha256) = 32", name="sessions_token_hash_ck"),
        sa.CheckConstraint("octet_length(csrf_sha256) = 32", name="sessions_csrf_hash_ck"),
        sa.CheckConstraint(
            "idle_expires_at <= absolute_expires_at AND absolute_expires_at > created_at",
            name="sessions_expiry_order_ck",
        ),
    )
    op.create_index(
        "sessions_user_active_idx",
        "sessions",
        ["user_id", "absolute_expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "lead_status_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "inquiry_id",
            UUID(as_uuid=True),
            sa.ForeignKey("inquiries.id", name="lead_status_history_inquiry_id_fkey", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", name="lead_status_history_actor_user_id_fkey", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("from_status", sa.Text(), nullable=False),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "from_status IN ('new','contacted','qualified','viewing','won','lost','closed')",
            name="history_from_status_ck",
        ),
        sa.CheckConstraint(
            "to_status IN ('new','contacted','qualified','viewing','won','lost','closed')",
            name="history_to_status_ck",
        ),
        sa.CheckConstraint("from_status <> to_status", name="history_change_ck"),
    )
    op.create_index(
        "lead_status_history_inquiry_idx", "lead_status_history", ["inquiry_id", "created_at", "id"]
    )
    op.create_table(
        "audit_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "actor_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", name="audit_events_actor_user_id_fkey", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", UUID(as_uuid=True), nullable=False),
        sa.Column("context", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("char_length(action) BETWEEN 1 AND 80", name="audit_action_len_ck"),
        sa.CheckConstraint("char_length(entity_type) BETWEEN 1 AND 40", name="audit_entity_type_len_ck"),
        sa.CheckConstraint("jsonb_typeof(context) = 'object'", name="audit_context_object_ck"),
    )
    op.create_index("audit_entity_idx", "audit_events", ["entity_type", "entity_id", "created_at", "id"])
    op.add_column("inquiries", sa.Column("assigned_user_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "inquiries_assigned_user_fk",
        "inquiries",
        "users",
        ["assigned_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "inquiries_assignee_idx",
        "inquiries",
        ["assigned_user_id", sa.text("submitted_at DESC")],
        postgresql_where=sa.text("assigned_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("inquiries_assignee_idx", table_name="inquiries")
    op.drop_constraint("inquiries_assigned_user_fk", "inquiries", type_="foreignkey")
    op.drop_column("inquiries", "assigned_user_id")
    op.drop_index("audit_entity_idx", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("lead_status_history_inquiry_idx", table_name="lead_status_history")
    op.drop_table("lead_status_history")
    op.drop_index("sessions_user_active_idx", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("users")
