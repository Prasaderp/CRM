from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── properties ────────────────────────────────────────────────────────────
    op.create_table(
        "properties",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("locality", sa.Text(), nullable=False),
        sa.Column("price_label", sa.Text(), nullable=True),
        sa.Column("project_registration_number", sa.Text(), nullable=True),
        sa.Column("registration_authority_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("slug", name="properties_slug_key"),
        sa.CheckConstraint(
            "slug = lower(slug) AND slug ~ '^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$'",
            name="properties_slug_ck",
        ),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 160", name="properties_title_len_ck"),
        sa.CheckConstraint("char_length(summary) <= 2000", name="properties_summary_len_ck"),
        sa.CheckConstraint("char_length(locality) BETWEEN 1 AND 160", name="properties_locality_len_ck"),
        sa.CheckConstraint(
            "price_label IS NULL OR char_length(price_label) <= 80",
            name="properties_price_len_ck",
        ),
        sa.CheckConstraint(
            "project_registration_number IS NULL OR char_length(project_registration_number) <= 100",
            name="properties_reg_len_ck",
        ),
        sa.CheckConstraint(
            "registration_authority_url IS NULL OR char_length(registration_authority_url) <= 2048",
            name="properties_reg_url_len_ck",
        ),
    )

    # ── contacts ──────────────────────────────────────────────────────────────
    op.create_table(
        "contacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("normalized_email", sa.Text(), nullable=True),
        sa.Column("normalized_phone", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("char_length(full_name) BETWEEN 1 AND 120", name="contacts_name_len_ck"),
        sa.CheckConstraint(
            "normalized_email IS NULL OR char_length(normalized_email) <= 254",
            name="contacts_email_len_ck",
        ),
        sa.CheckConstraint(
            r"normalized_phone IS NULL OR normalized_phone ~ '^\+[1-9][0-9]{7,14}$'",
            name="contacts_phone_ck",
        ),
        sa.CheckConstraint(
            "normalized_email IS NOT NULL OR normalized_phone IS NOT NULL",
            name="contacts_method_ck",
        ),
    )
    op.create_index(
        "contacts_email_idx",
        "contacts",
        ["normalized_email"],
        postgresql_where=sa.text("normalized_email IS NOT NULL"),
    )
    op.create_index(
        "contacts_phone_idx",
        "contacts",
        ["normalized_phone"],
        postgresql_where=sa.text("normalized_phone IS NOT NULL"),
    )

    # ── inquiries ─────────────────────────────────────────────────────────────
    op.create_table(
        "inquiries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("public_reference", sa.Text(), nullable=False),
        sa.Column(
            "contact_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "property_id",
            UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_platform", sa.Text(), nullable=False),
        sa.Column("capture_surface", sa.Text(), nullable=False, server_default=sa.text("'website'")),
        sa.Column("form_version", sa.Text(), nullable=False),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("budget_band", sa.Text(), nullable=True),
        sa.Column("timeframe", sa.Text(), nullable=True),
        sa.Column("preferred_contact_method", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'new'")),
        sa.Column("dedupe_state", sa.Text(), nullable=False, server_default=sa.text("'clear'")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("public_reference", name="inquiries_public_reference_key"),
        sa.CheckConstraint(r"public_reference ~ '^RE-[A-Z0-9]{10}$'", name="inquiries_public_ref_ck"),
        sa.CheckConstraint(
            "source_platform IN ('facebook','instagram','tiktok','x','direct','unknown')", name="inquiries_source_ck"
        ),
        sa.CheckConstraint("capture_surface IN ('website')", name="inquiries_surface_ck"),
        sa.CheckConstraint("char_length(form_version) BETWEEN 1 AND 40", name="inquiries_form_version_len_ck"),
        sa.CheckConstraint(
            "intent IS NULL OR intent IN ('buy','rent','sell','information')", name="inquiries_intent_ck"
        ),
        sa.CheckConstraint("budget_band IS NULL OR char_length(budget_band) <= 40", name="inquiries_budget_len_ck"),
        sa.CheckConstraint("timeframe IS NULL OR char_length(timeframe) <= 40", name="inquiries_timeframe_len_ck"),
        sa.CheckConstraint(
            "preferred_contact_method IS NULL OR preferred_contact_method IN ('email','phone','whatsapp','no_preference')",
            name="inquiries_contact_method_ck",
        ),
        sa.CheckConstraint("message IS NULL OR char_length(message) <= 2000", name="inquiries_message_len_ck"),
        sa.CheckConstraint(
            "status IN ('new','contacted','qualified','viewing','won','lost','closed')",
            name="inquiries_status_ck",
        ),
        sa.CheckConstraint("dedupe_state IN ('clear','review')", name="inquiries_dedupe_ck"),
        sa.CheckConstraint("version > 0", name="inquiries_version_ck"),
    )
    op.create_index("inquiries_submitted_idx", "inquiries", [sa.text("submitted_at DESC"), sa.text("id DESC")])
    op.create_index("inquiries_status_idx", "inquiries", ["status", sa.text("submitted_at DESC")])
    op.create_index("inquiries_contact_idx", "inquiries", ["contact_id", sa.text("submitted_at DESC")])
    op.create_index("inquiries_property_idx", "inquiries", ["property_id", sa.text("submitted_at DESC")])

    # ── consent_records ───────────────────────────────────────────────────────
    op.create_table(
        "consent_records",
        sa.Column(
            "inquiry_id",
            UUID(as_uuid=True),
            sa.ForeignKey("inquiries.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("notice_version", sa.Text(), nullable=False),
        sa.Column("notice_text", sa.Text(), nullable=False),
        sa.Column("notice_sha256", sa.LargeBinary(32), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column("requested_contact", sa.Boolean(), nullable=False),
        sa.Column("marketing_opt_in", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ad_measurement_opt_in", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("capture_surface", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "char_length(notice_version) BETWEEN 1 AND 40",
            name="consent_notice_version_len_ck",
        ),
        sa.CheckConstraint(
            "char_length(notice_text) BETWEEN 1 AND 8000",
            name="consent_notice_text_len_ck",
        ),
        sa.CheckConstraint(
            "octet_length(notice_sha256) = 32",
            name="consent_notice_hash_ck",
        ),
        sa.CheckConstraint(
            "char_length(locale) BETWEEN 2 AND 20",
            name="consent_locale_len_ck",
        ),
        sa.CheckConstraint("requested_contact", name="consent_contact_ck"),
        sa.CheckConstraint("capture_surface IN ('website')", name="consent_surface_ck"),
    )

    # ── attribution_touches ───────────────────────────────────────────────────
    op.create_table(
        "attribution_touches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "inquiry_id",
            UUID(as_uuid=True),
            sa.ForeignKey("inquiries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("touch_type", sa.Text(), nullable=False, server_default=sa.text("'submission'")),
        sa.Column("utm_source", sa.Text(), nullable=True),
        sa.Column("utm_medium", sa.Text(), nullable=True),
        sa.Column("utm_campaign", sa.Text(), nullable=True),
        sa.Column("utm_content", sa.Text(), nullable=True),
        sa.Column("utm_term", sa.Text(), nullable=True),
        sa.Column("click_id_kind", sa.Text(), nullable=True),
        sa.Column("click_id_value", sa.Text(), nullable=True),
        sa.Column("landing_path", sa.Text(), nullable=False),
        sa.Column("referrer_origin_path", sa.Text(), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("inquiry_id", "touch_type", name="attribution_one_touch_uk"),
        sa.CheckConstraint("touch_type IN ('submission')", name="attribution_touch_ck"),
        sa.CheckConstraint(
            "utm_source IS NULL OR char_length(utm_source) <= 100",
            name="attribution_source_len_ck",
        ),
        sa.CheckConstraint(
            "utm_medium IS NULL OR char_length(utm_medium) <= 100",
            name="attribution_medium_len_ck",
        ),
        sa.CheckConstraint(
            "utm_campaign IS NULL OR char_length(utm_campaign) <= 200",
            name="attribution_campaign_len_ck",
        ),
        sa.CheckConstraint(
            "utm_content IS NULL OR char_length(utm_content) <= 200",
            name="attribution_content_len_ck",
        ),
        sa.CheckConstraint(
            "utm_term IS NULL OR char_length(utm_term) <= 200",
            name="attribution_term_len_ck",
        ),
        sa.CheckConstraint(
            "click_id_kind IS NULL OR click_id_kind IN ('fbclid','ttclid','twclid')",
            name="attribution_click_kind_ck",
        ),
        sa.CheckConstraint(
            "click_id_value IS NULL OR char_length(click_id_value) <= 512",
            name="attribution_click_value_len_ck",
        ),
        sa.CheckConstraint(
            "(click_id_kind IS NULL) = (click_id_value IS NULL)",
            name="attribution_click_pair_ck",
        ),
        sa.CheckConstraint(
            "char_length(landing_path) BETWEEN 1 AND 2048",
            name="attribution_landing_len_ck",
        ),
        sa.CheckConstraint(
            "referrer_origin_path IS NULL OR char_length(referrer_origin_path) <= 2048",
            name="attribution_referrer_len_ck",
        ),
    )

    # ── idempotency_requests ──────────────────────────────────────────────────
    op.create_table(
        "idempotency_requests",
        sa.Column("endpoint", sa.Text(), primary_key=True, nullable=False),
        sa.Column("key", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("request_sha256", sa.LargeBinary(32), nullable=False),
        sa.Column(
            "inquiry_id",
            UUID(as_uuid=True),
            sa.ForeignKey("inquiries.id", ondelete="CASCADE", name="idempotency_inquiry_fk"),
            nullable=True,
        ),
        sa.Column("response_status", sa.SmallInteger(), nullable=True),
        sa.Column("response_body", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("char_length(endpoint) BETWEEN 1 AND 100", name="idempotency_endpoint_len_ck"),
        sa.CheckConstraint("octet_length(request_sha256) = 32", name="idempotency_hash_ck"),
        sa.CheckConstraint(
            "response_status IS NULL OR response_status BETWEEN 200 AND 599",
            name="idempotency_status_ck",
        ),
        sa.CheckConstraint(
            "(inquiry_id IS NULL) = (response_status IS NULL) AND (response_status IS NULL) = (response_body IS NULL)",
            name="idempotency_complete_ck",
        ),
        sa.CheckConstraint("expires_at > created_at", name="idempotency_expiry_ck"),
    )
    op.create_index("idempotency_expiry_idx", "idempotency_requests", ["expires_at"])

    # ── outbox_jobs ───────────────────────────────────────────────────────────
    op.create_table(
        "outbox_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("job_kind", sa.Text(), nullable=False),
        sa.Column("aggregate_id", UUID(as_uuid=True), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("smtp_message_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("dedupe_key", name="outbox_jobs_dedupe_key_key"),
        sa.CheckConstraint("job_kind IN ('lead_email')", name="outbox_kind_ck"),
        sa.CheckConstraint("state IN ('pending','processing','completed','dead')", name="outbox_state_ck"),
        sa.CheckConstraint("attempts BETWEEN 0 AND 12", name="outbox_attempts_ck"),
        sa.CheckConstraint("char_length(dedupe_key) BETWEEN 1 AND 160", name="outbox_dedupe_len_ck"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="outbox_payload_object_ck"),
        sa.CheckConstraint(
            "last_error_code IS NULL OR char_length(last_error_code) <= 80",
            name="outbox_error_len_ck",
        ),
        sa.CheckConstraint(
            "smtp_message_id IS NULL OR char_length(smtp_message_id) <= 254",
            name="outbox_message_id_len_ck",
        ),
        sa.CheckConstraint("(locked_by IS NULL) = (locked_at IS NULL)", name="outbox_lock_pair_ck"),
        sa.CheckConstraint("(state = 'completed') = (completed_at IS NOT NULL)", name="outbox_completion_ck"),
    )
    op.create_index(
        "outbox_due_idx",
        "outbox_jobs",
        ["available_at", "id"],
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_index(
        "outbox_stale_idx",
        "outbox_jobs",
        ["locked_at", "id"],
        postgresql_where=sa.text("state = 'processing'"),
    )


def downgrade() -> None:
    # WARNING: downgrade is permitted only in local/test environments.
    # Never run destructive downgrade against production data without explicit sign-off.
    # Drop in reverse foreign-key dependency order.
    op.drop_table("outbox_jobs")
    op.drop_table("idempotency_requests")
    op.drop_table("attribution_touches")
    op.drop_table("consent_records")
    op.drop_table("inquiries")
    op.drop_table("contacts")
    op.drop_table("properties")
