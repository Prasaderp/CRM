from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from real_estate_crm.db import Base

if TYPE_CHECKING:
    from real_estate_crm.auth.models import LeadStatusHistory, User


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    locality: Mapped[str] = mapped_column(Text, nullable=False)
    price_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_registration_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_authority_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    inquiries: Mapped[list["Inquiry"]] = relationship(back_populates="property")

    __table_args__ = (
        CheckConstraint(
            "slug = lower(slug) AND slug ~ '^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$'",
            name="properties_slug_ck",
        ),
        CheckConstraint("char_length(title) BETWEEN 1 AND 160", name="properties_title_len_ck"),
        CheckConstraint("char_length(summary) <= 2000", name="properties_summary_len_ck"),
        CheckConstraint("char_length(locality) BETWEEN 1 AND 160", name="properties_locality_len_ck"),
        CheckConstraint("price_label IS NULL OR char_length(price_label) <= 80", name="properties_price_len_ck"),
        CheckConstraint(
            "project_registration_number IS NULL OR char_length(project_registration_number) <= 100",
            name="properties_reg_len_ck",
        ),
        CheckConstraint(
            "registration_authority_url IS NULL OR char_length(registration_authority_url) <= 2048",
            name="properties_reg_url_len_ck",
        ),
    )


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_email: Mapped[str | None] = mapped_column(Text, nullable=True, index=False)
    normalized_phone: Mapped[str | None] = mapped_column(Text, nullable=True, index=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")

    inquiries: Mapped[list["Inquiry"]] = relationship(back_populates="contact")

    __table_args__ = (
        CheckConstraint("char_length(full_name) BETWEEN 1 AND 120", name="contacts_name_len_ck"),
        CheckConstraint(
            "normalized_email IS NULL OR char_length(normalized_email) <= 254",
            name="contacts_email_len_ck",
        ),
        CheckConstraint(
            r"normalized_phone IS NULL OR normalized_phone ~ '^\+[1-9][0-9]{7,14}$'",
            name="contacts_phone_ck",
        ),
        CheckConstraint(
            "normalized_email IS NOT NULL OR normalized_phone IS NOT NULL",
            name="contacts_method_ck",
        ),
        # Partial indexes are defined in the migration; ORM Index objects here
        # would duplicate them. Alembic autogenerate drift-checks these via
        # the migration's explicit CREATE INDEX statements.
        Index("contacts_email_idx", "normalized_email", postgresql_where="normalized_email IS NOT NULL"),
        Index("contacts_phone_idx", "normalized_phone", postgresql_where="normalized_phone IS NOT NULL"),
    )


class Inquiry(Base):
    __tablename__ = "inquiries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    public_reference: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=False
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source_platform: Mapped[str] = mapped_column(Text, nullable=False)
    capture_surface: Mapped[str] = mapped_column(Text, nullable=False, server_default="website")
    form_version: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget_band: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeframe: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_contact_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="new")
    dedupe_state: Mapped[str] = mapped_column(Text, nullable=False, server_default="clear")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    contact: Mapped["Contact"] = relationship(back_populates="inquiries")
    property: Mapped["Property"] = relationship(back_populates="inquiries")
    consent_record: Mapped["ConsentRecord | None"] = relationship(back_populates="inquiry")
    attribution_touches: Mapped[list["AttributionTouch"]] = relationship(back_populates="inquiry")
    idempotency_requests: Mapped[list["IdempotencyRequest"]] = relationship(back_populates="inquiry")
    outbox_jobs: Mapped[list["OutboxJob"]] = relationship(
        foreign_keys="OutboxJob.aggregate_id",
        primaryjoin="Inquiry.id == OutboxJob.aggregate_id",
        viewonly=True,
    )
    assigned_user: Mapped["User | None"] = relationship(back_populates="assigned_inquiries")
    status_history: Mapped[list["LeadStatusHistory"]] = relationship(back_populates="inquiry")

    __table_args__ = (
        CheckConstraint(r"public_reference ~ '^RE-[A-Z0-9]{10}$'", name="inquiries_public_ref_ck"),
        CheckConstraint(
            "source_platform IN ('facebook','instagram','tiktok','x','direct','unknown')",
            name="inquiries_source_ck",
        ),
        CheckConstraint("capture_surface IN ('website')", name="inquiries_surface_ck"),
        CheckConstraint("char_length(form_version) BETWEEN 1 AND 40", name="inquiries_form_version_len_ck"),
        CheckConstraint(
            "intent IS NULL OR intent IN ('buy','rent','sell','information')",
            name="inquiries_intent_ck",
        ),
        CheckConstraint(
            "budget_band IS NULL OR char_length(budget_band) <= 40",
            name="inquiries_budget_len_ck",
        ),
        CheckConstraint(
            "timeframe IS NULL OR char_length(timeframe) <= 40",
            name="inquiries_timeframe_len_ck",
        ),
        CheckConstraint(
            "preferred_contact_method IS NULL OR preferred_contact_method IN ('email','phone','whatsapp','no_preference')",
            name="inquiries_contact_method_ck",
        ),
        CheckConstraint("message IS NULL OR char_length(message) <= 2000", name="inquiries_message_len_ck"),
        CheckConstraint(
            "status IN ('new','contacted','qualified','viewing','won','lost','closed')",
            name="inquiries_status_ck",
        ),
        CheckConstraint("dedupe_state IN ('clear','review')", name="inquiries_dedupe_ck"),
        CheckConstraint("version > 0", name="inquiries_version_ck"),
        Index("inquiries_submitted_idx", text("submitted_at DESC"), text("id DESC")),
        Index("inquiries_status_idx", "status", text("submitted_at DESC")),
        Index("inquiries_contact_idx", "contact_id", text("submitted_at DESC")),
        Index("inquiries_property_idx", "property_id", text("submitted_at DESC")),
        Index(
            "inquiries_assignee_idx",
            "assigned_user_id",
            text("submitted_at DESC"),
            postgresql_where="assigned_user_id IS NOT NULL",
        ),
    )


class ConsentRecord(Base):
    __tablename__ = "consent_records"

    inquiry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inquiries.id", ondelete="CASCADE"),
        primary_key=True,
    )
    notice_version: Mapped[str] = mapped_column(Text, nullable=False)
    notice_text: Mapped[str] = mapped_column(Text, nullable=False)
    notice_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    locale: Mapped[str] = mapped_column(Text, nullable=False)
    requested_contact: Mapped[bool] = mapped_column(Boolean, nullable=False)
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    ad_measurement_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    capture_surface: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")

    inquiry: Mapped["Inquiry"] = relationship(back_populates="consent_record")

    __table_args__ = (
        CheckConstraint(
            "char_length(notice_version) BETWEEN 1 AND 40",
            name="consent_notice_version_len_ck",
        ),
        CheckConstraint(
            "char_length(notice_text) BETWEEN 1 AND 8000",
            name="consent_notice_text_len_ck",
        ),
        CheckConstraint("octet_length(notice_sha256) = 32", name="consent_notice_hash_ck"),
        CheckConstraint("char_length(locale) BETWEEN 2 AND 20", name="consent_locale_len_ck"),
        CheckConstraint("requested_contact", name="consent_contact_ck"),
        CheckConstraint("capture_surface IN ('website')", name="consent_surface_ck"),
    )


class AttributionTouch(Base):
    __tablename__ = "attribution_touches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    inquiry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inquiries.id", ondelete="CASCADE"),
        nullable=False,
    )
    touch_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="submission")
    utm_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_term: Mapped[str | None] = mapped_column(Text, nullable=True)
    click_id_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    click_id_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    landing_path: Mapped[str] = mapped_column(Text, nullable=False)
    referrer_origin_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")

    inquiry: Mapped["Inquiry"] = relationship(back_populates="attribution_touches")

    __table_args__ = (
        UniqueConstraint("inquiry_id", "touch_type", name="attribution_one_touch_uk"),
        CheckConstraint("touch_type IN ('submission')", name="attribution_touch_ck"),
        CheckConstraint(
            "utm_source IS NULL OR char_length(utm_source) <= 100",
            name="attribution_source_len_ck",
        ),
        CheckConstraint(
            "utm_medium IS NULL OR char_length(utm_medium) <= 100",
            name="attribution_medium_len_ck",
        ),
        CheckConstraint(
            "utm_campaign IS NULL OR char_length(utm_campaign) <= 200",
            name="attribution_campaign_len_ck",
        ),
        CheckConstraint(
            "utm_content IS NULL OR char_length(utm_content) <= 200",
            name="attribution_content_len_ck",
        ),
        CheckConstraint(
            "utm_term IS NULL OR char_length(utm_term) <= 200",
            name="attribution_term_len_ck",
        ),
        CheckConstraint(
            "click_id_kind IS NULL OR click_id_kind IN ('fbclid','ttclid','twclid')",
            name="attribution_click_kind_ck",
        ),
        CheckConstraint(
            "click_id_value IS NULL OR char_length(click_id_value) <= 512",
            name="attribution_click_value_len_ck",
        ),
        CheckConstraint(
            "(click_id_kind IS NULL) = (click_id_value IS NULL)",
            name="attribution_click_pair_ck",
        ),
        CheckConstraint(
            "char_length(landing_path) BETWEEN 1 AND 2048",
            name="attribution_landing_len_ck",
        ),
        CheckConstraint(
            "referrer_origin_path IS NULL OR char_length(referrer_origin_path) <= 2048",
            name="attribution_referrer_len_ck",
        ),
    )


class IdempotencyRequest(Base):
    __tablename__ = "idempotency_requests"

    endpoint: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    request_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    inquiry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inquiries.id", ondelete="CASCADE"), nullable=True
    )
    response_status: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    inquiry: Mapped["Inquiry | None"] = relationship(back_populates="idempotency_requests")

    __table_args__ = (
        CheckConstraint("char_length(endpoint) BETWEEN 1 AND 100", name="idempotency_endpoint_len_ck"),
        CheckConstraint("octet_length(request_sha256) = 32", name="idempotency_hash_ck"),
        CheckConstraint(
            "response_status IS NULL OR response_status BETWEEN 200 AND 599",
            name="idempotency_status_ck",
        ),
        CheckConstraint(
            "(inquiry_id IS NULL) = (response_status IS NULL) AND (response_status IS NULL) = (response_body IS NULL)",
            name="idempotency_complete_ck",
        ),
        CheckConstraint("expires_at > created_at", name="idempotency_expiry_ck"),
        Index("idempotency_expiry_idx", "expires_at"),
    )


class OutboxJob(Base):
    __tablename__ = "outbox_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    job_kind: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    locked_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Viewonly relationship: OutboxJob links to Inquiry via aggregate_id when job_kind='lead_email'
    # We do NOT enforce an FK here in ORM (the migration does it via aggregate_id semantics).

    __table_args__ = (
        CheckConstraint("job_kind IN ('lead_email')", name="outbox_kind_ck"),
        CheckConstraint("state IN ('pending','processing','completed','dead')", name="outbox_state_ck"),
        CheckConstraint("attempts BETWEEN 0 AND 12", name="outbox_attempts_ck"),
        CheckConstraint("char_length(dedupe_key) BETWEEN 1 AND 160", name="outbox_dedupe_len_ck"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="outbox_payload_object_ck"),
        CheckConstraint(
            "last_error_code IS NULL OR char_length(last_error_code) <= 80",
            name="outbox_error_len_ck",
        ),
        CheckConstraint(
            "smtp_message_id IS NULL OR char_length(smtp_message_id) <= 254",
            name="outbox_message_id_len_ck",
        ),
        CheckConstraint("(locked_by IS NULL) = (locked_at IS NULL)", name="outbox_lock_pair_ck"),
        CheckConstraint("(state = 'completed') = (completed_at IS NOT NULL)", name="outbox_completion_ck"),
        Index("outbox_due_idx", "available_at", "id", postgresql_where="state = 'pending'"),
        Index("outbox_stale_idx", "locked_at", "id", postgresql_where="state = 'processing'"),
    )


# Register cross-domain tables before SQLAlchemy resolves Inquiry's user relationships.
import real_estate_crm.auth.models  # noqa: E402,F401
