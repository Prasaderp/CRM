from __future__ import annotations

import uuid
from datetime import datetime
from typing import Mapping

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from real_estate_crm.db import Base

AUDIT_CONTEXT_KEYS = frozenset(
    {"from_status", "to_status", "from_assignee_id", "to_assignee_id", "reason_code"}
)


def audit_context(values: Mapping[str, str | None]) -> dict[str, str | None]:
    unknown = values.keys() - AUDIT_CONTEXT_KEYS
    if unknown:
        raise ValueError(f"unsupported audit context keys: {', '.join(sorted(unknown))}")
    if any(value is not None and (not isinstance(value, str) or len(value) > 120) for value in values.values()):
        raise ValueError("audit context values must be nullable strings of at most 120 characters")
    return dict(values)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    normalized_email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")

    sessions: Mapped[list["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    assigned_inquiries: Mapped[list["Inquiry"]] = relationship(back_populates="assigned_user")
    status_changes: Mapped[list["LeadStatusHistory"]] = relationship(back_populates="actor")
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="actor")

    __table_args__ = (
        CheckConstraint("char_length(normalized_email) <= 254", name="users_email_len_ck"),
        CheckConstraint("char_length(display_name) BETWEEN 1 AND 120", name="users_name_len_ck"),
        CheckConstraint("role IN ('admin','agent')", name="users_role_ck"),
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    csrf_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="sessions")

    __table_args__ = (
        CheckConstraint("octet_length(token_sha256) = 32", name="sessions_token_hash_ck"),
        CheckConstraint("octet_length(csrf_sha256) = 32", name="sessions_csrf_hash_ck"),
        CheckConstraint(
            "idle_expires_at <= absolute_expires_at AND absolute_expires_at > created_at",
            name="sessions_expiry_order_ck",
        ),
        Index(
            "sessions_user_active_idx",
            "user_id",
            "absolute_expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )


class LeadStatusHistory(Base):
    __tablename__ = "lead_status_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    inquiry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inquiries.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[str] = mapped_column(Text, nullable=False)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")

    inquiry: Mapped["Inquiry"] = relationship(back_populates="status_history")
    actor: Mapped["User"] = relationship(back_populates="status_changes")

    __table_args__ = (
        CheckConstraint(
            "from_status IN ('new','contacted','qualified','viewing','won','lost','closed')",
            name="history_from_status_ck",
        ),
        CheckConstraint(
            "to_status IN ('new','contacted','qualified','viewing','won','lost','closed')",
            name="history_to_status_ck",
        ),
        CheckConstraint("from_status <> to_status", name="history_change_ck"),
        Index("lead_status_history_inquiry_idx", "inquiry_id", "created_at", "id"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    context: Mapped[dict[str, str | None]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")

    actor: Mapped["User | None"] = relationship(back_populates="audit_events")

    @validates("context")
    def _validate_context(
        self, _key: str, values: Mapping[str, str | None]
    ) -> dict[str, str | None]:
        return audit_context(values)

    __table_args__ = (
        CheckConstraint("char_length(action) BETWEEN 1 AND 80", name="audit_action_len_ck"),
        CheckConstraint("char_length(entity_type) BETWEEN 1 AND 40", name="audit_entity_type_len_ck"),
        CheckConstraint("jsonb_typeof(context) = 'object'", name="audit_context_object_ck"),
        Index("audit_entity_idx", "entity_type", "entity_id", "created_at", "id"),
    )


from real_estate_crm.leads.models import Inquiry  # noqa: E402

__all__ = [
    "AUDIT_CONTEXT_KEYS",
    "AuditEvent",
    "LeadStatusHistory",
    "Session",
    "User",
    "audit_context",
]
