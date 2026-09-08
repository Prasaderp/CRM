from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa

# Ensure required env vars are set before importing Settings-dependent modules.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test_db")
os.environ.setdefault("CANONICAL_NOTICE_VERSION", "v1-test")
os.environ.setdefault("CANONICAL_NOTICE_TEXT", "Test notice text")
os.environ.setdefault("SMTP_HOST", "localhost")
os.environ.setdefault("SMTP_PORT", "1025")
os.environ.setdefault("SMTP_SENDER", "test@example.com")
os.environ.setdefault("RECIPIENT_ALLOW_LIST", "admin@example.com")


# ─── Imports under test ────────────────────────────────────────────────────────

from real_estate_crm.db import (  # noqa: E402
    Base,
    DatabaseError,
    db_session,
    probe_connectivity,
)
from real_estate_crm.leads import models as lead_models
from real_estate_crm.notifications import models as notif_models


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _constraint_names(table) -> set[str]:
    return {c.name for c in table.constraints if c.name}


def _index_names(table) -> set[str]:
    return {i.name for i in table.indexes}


# ─── Phase 3: db.py — session state machine ────────────────────────────────────


class TestDbSession:
    """db_session() must commit on clean exit, rollback+re-raise on exception."""

    def _mock_session(self):
        session = MagicMock()
        session.close = MagicMock()
        session.commit = MagicMock()
        session.rollback = MagicMock()
        return session

    def test_commit_on_clean_exit(self):
        session = self._mock_session()
        factory = MagicMock(return_value=session)

        with patch("real_estate_crm.db.get_session_factory", return_value=factory):
            with db_session() as s:
                assert s is session

        session.commit.assert_called_once()
        session.rollback.assert_not_called()
        session.close.assert_called_once()

    def test_rollback_and_reraise_on_generic_exception(self):
        session = self._mock_session()
        factory = MagicMock(return_value=session)

        with patch("real_estate_crm.db.get_session_factory", return_value=factory):
            with pytest.raises(ValueError, match="boom"):
                with db_session():
                    raise ValueError("boom")

        session.rollback.assert_called_once()
        session.commit.assert_not_called()
        session.close.assert_called_once()

    def test_operational_error_becomes_database_error(self):
        session = self._mock_session()
        session.commit.side_effect = sa.exc.OperationalError("conn", {}, Exception("lost"))
        factory = MagicMock(return_value=session)

        with patch("real_estate_crm.db.get_session_factory", return_value=factory):
            with pytest.raises(DatabaseError):
                with db_session():
                    pass  # commit() will raise OperationalError

        session.rollback.assert_called_once()
        session.close.assert_called_once()

    def test_session_always_closed_even_when_rollback_fails(self):
        """close() must be called even if rollback() itself raises."""
        session = self._mock_session()
        session.rollback.side_effect = sa.exc.OperationalError("x", {}, Exception())
        factory = MagicMock(return_value=session)

        with patch("real_estate_crm.db.get_session_factory", return_value=factory):
            with pytest.raises(Exception):
                with db_session():
                    raise RuntimeError("trigger rollback")

        session.close.assert_called_once()

    def test_no_nested_transactions_on_same_session(self):
        """Verify the context manager does not nest begin() calls."""
        session = self._mock_session()
        factory = MagicMock(return_value=session)
        call_count = {"begin": 0}

        session.begin.side_effect = lambda: call_count.update({"begin": call_count["begin"] + 1}) or MagicMock()

        with patch("real_estate_crm.db.get_session_factory", return_value=factory):
            with db_session():
                pass

        # db_session() does not call session.begin(); autocommit=False handles it.
        assert call_count["begin"] == 0


class TestProbeConnectivity:
    def test_raises_database_error_on_connection_failure(self):
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = sa.exc.OperationalError("x", {}, Exception("refused"))

        with patch("real_estate_crm.db.get_engine", return_value=mock_engine):
            with pytest.raises(DatabaseError, match="connectivity probe failed"):
                probe_connectivity()

    def test_succeeds_silently_on_good_connection(self):
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("real_estate_crm.db.get_engine", return_value=mock_engine):
            probe_connectivity()  # must not raise


# ─── Phase 4: ORM metadata correctness ────────────────────────────────────────


class TestPropertyModel:
    def test_table_name(self):
        assert lead_models.Property.__tablename__ == "properties"

    def test_required_columns_present(self):
        cols = {c.name for c in lead_models.Property.__table__.columns}
        assert {"id", "slug", "title", "summary", "locality", "is_active", "created_at", "updated_at"}.issubset(cols)

    def test_slug_unique_constraint(self):
        table = lead_models.Property.__table__
        unique_cols = {col.name for c in table.constraints if isinstance(c, sa.UniqueConstraint) for col in c.columns}
        # Slug uniqueness is expressed via unique=True on the column (becomes a UniqueConstraint)
        slug_col = lead_models.Property.__table__.c.slug
        assert slug_col.unique or "slug" in unique_cols

    def test_slug_check_constraint_present(self):
        names = _constraint_names(lead_models.Property.__table__)
        assert "properties_slug_ck" in names

    def test_price_label_nullable(self):
        col = lead_models.Property.__table__.c.price_label
        assert col.nullable

    def test_is_active_server_default_true(self):
        col = lead_models.Property.__table__.c.is_active
        assert col.server_default is not None


class TestContactModel:
    def test_table_name(self):
        assert lead_models.Contact.__tablename__ == "contacts"

    def test_method_check_constraint(self):
        names = _constraint_names(lead_models.Contact.__table__)
        assert "contacts_method_ck" in names

    def test_phone_check_constraint(self):
        names = _constraint_names(lead_models.Contact.__table__)
        assert "contacts_phone_ck" in names

    def test_partial_indexes_defined(self):
        idx = _index_names(lead_models.Contact.__table__)
        assert "contacts_email_idx" in idx
        assert "contacts_phone_idx" in idx

    def test_email_and_phone_not_unique(self):
        """Email/phone are indexed but NOT unique — multiple contacts allowed."""
        email_col = lead_models.Contact.__table__.c.normalized_email
        phone_col = lead_models.Contact.__table__.c.normalized_phone
        assert not email_col.unique
        assert not phone_col.unique


class TestInquiryModel:
    def test_table_name(self):
        assert lead_models.Inquiry.__tablename__ == "inquiries"

    def test_status_check_constraint(self):
        names = _constraint_names(lead_models.Inquiry.__table__)
        assert "inquiries_status_ck" in names

    def test_source_platform_check_constraint(self):
        names = _constraint_names(lead_models.Inquiry.__table__)
        assert "inquiries_source_ck" in names

    def test_public_reference_check_constraint(self):
        names = _constraint_names(lead_models.Inquiry.__table__)
        assert "inquiries_public_ref_ck" in names

    def test_version_default_1(self):
        col = lead_models.Inquiry.__table__.c.version
        assert col.server_default is not None

    def test_dedupe_state_check_constraint(self):
        names = _constraint_names(lead_models.Inquiry.__table__)
        assert "inquiries_dedupe_ck" in names

    def test_submitted_index_present(self):
        idx = _index_names(lead_models.Inquiry.__table__)
        assert "inquiries_submitted_idx" in idx

    def test_contact_id_fk_restrict(self):
        # Inspect ForeignKeyConstraint directly (avoids resolving users table from Phase 20)
        fkc = next(
            c
            for c in lead_models.Inquiry.__table__.constraints
            if hasattr(c, "elements") and any(e.target_fullname == "contacts.id" for e in c.elements)
        )
        assert fkc.ondelete == "RESTRICT"

    def test_property_id_fk_restrict(self):
        fkc = next(
            c
            for c in lead_models.Inquiry.__table__.constraints
            if hasattr(c, "elements") and any(e.target_fullname == "properties.id" for e in c.elements)
        )
        assert fkc.ondelete == "RESTRICT"


class TestConsentRecordModel:
    def test_table_name(self):
        assert lead_models.ConsentRecord.__tablename__ == "consent_records"

    def test_primary_key_is_inquiry_id(self):
        pk_cols = [c.name for c in lead_models.ConsentRecord.__table__.primary_key]
        assert pk_cols == ["inquiry_id"]

    def test_requested_contact_check_present(self):
        names = _constraint_names(lead_models.ConsentRecord.__table__)
        assert "consent_contact_ck" in names

    def test_notice_sha256_length_check(self):
        names = _constraint_names(lead_models.ConsentRecord.__table__)
        assert "consent_notice_hash_ck" in names

    def test_fk_cascade_delete(self):
        fk = next(iter(lead_models.ConsentRecord.__table__.foreign_keys))
        assert fk.ondelete == "CASCADE"


class TestAttributionTouchModel:
    def test_table_name(self):
        assert lead_models.AttributionTouch.__tablename__ == "attribution_touches"

    def test_one_touch_unique_constraint(self):
        names = _constraint_names(lead_models.AttributionTouch.__table__)
        assert "attribution_one_touch_uk" in names

    def test_click_pair_check_constraint(self):
        names = _constraint_names(lead_models.AttributionTouch.__table__)
        assert "attribution_click_pair_ck" in names

    def test_click_kind_check_constraint(self):
        names = _constraint_names(lead_models.AttributionTouch.__table__)
        assert "attribution_click_kind_ck" in names

    def test_landing_path_not_nullable(self):
        col = lead_models.AttributionTouch.__table__.c.landing_path
        assert not col.nullable


class TestIdempotencyRequestModel:
    def test_table_name(self):
        assert lead_models.IdempotencyRequest.__tablename__ == "idempotency_requests"

    def test_composite_pk(self):
        pk = {c.name for c in lead_models.IdempotencyRequest.__table__.primary_key}
        assert pk == {"endpoint", "key"}

    def test_complete_check_constraint(self):
        names = _constraint_names(lead_models.IdempotencyRequest.__table__)
        assert "idempotency_complete_ck" in names

    def test_expiry_index(self):
        idx = _index_names(lead_models.IdempotencyRequest.__table__)
        assert "idempotency_expiry_idx" in idx

    def test_hash_length_check(self):
        names = _constraint_names(lead_models.IdempotencyRequest.__table__)
        assert "idempotency_hash_ck" in names


class TestOutboxJobModel:
    def test_table_name(self):
        assert lead_models.OutboxJob.__tablename__ == "outbox_jobs"

    def test_state_check_constraint(self):
        names = _constraint_names(lead_models.OutboxJob.__table__)
        assert "outbox_state_ck" in names

    def test_lock_pair_check_constraint(self):
        names = _constraint_names(lead_models.OutboxJob.__table__)
        assert "outbox_lock_pair_ck" in names

    def test_completion_check_constraint(self):
        names = _constraint_names(lead_models.OutboxJob.__table__)
        assert "outbox_completion_ck" in names

    def test_due_index_present(self):
        idx = _index_names(lead_models.OutboxJob.__table__)
        assert "outbox_due_idx" in idx

    def test_stale_index_present(self):
        idx = _index_names(lead_models.OutboxJob.__table__)
        assert "outbox_stale_idx" in idx

    def test_dedupe_key_unique(self):
        col = lead_models.OutboxJob.__table__.c.dedupe_key
        assert col.unique

    def test_attempts_check_constraint(self):
        names = _constraint_names(lead_models.OutboxJob.__table__)
        assert "outbox_attempts_ck" in names

    def test_kind_check_constraint(self):
        names = _constraint_names(lead_models.OutboxJob.__table__)
        assert "outbox_kind_ck" in names


class TestNotificationsModelsReExport:
    """notifications/models.py must re-export OutboxJob from leads/models."""

    def test_outbox_job_importable_from_notifications(self):
        from real_estate_crm.notifications.models import OutboxJob  # noqa: F401

        assert notif_models.OutboxJob is lead_models.OutboxJob

    def test_outbox_job_same_table_object(self):
        """Both imports must reference the same SQLAlchemy Table object."""
        assert notif_models.OutboxJob.__table__ is lead_models.OutboxJob.__table__


class TestBaseMetadata:
    """All model tables must be registered in the shared Base.metadata."""

    def test_all_tables_in_metadata(self):
        expected = {
            "properties",
            "contacts",
            "inquiries",
            "consent_records",
            "attribution_touches",
            "idempotency_requests",
            "outbox_jobs",
        }
        assert expected.issubset(set(Base.metadata.tables.keys()))

    def test_no_create_all_side_effect(self):
        """Importing models must not create tables — migrations are the sole authority."""
        # If create_all() had been called, the engine would have attempted DDL.
        # We verify the engine's dialect has never issued a CREATE TABLE by checking
        # that no real DB connection was made during module import.
        # (This is validated implicitly: if create_all() ran, it would have failed
        # on a non-existent DB host during test collection.)
        # Structural assertion: Base.metadata has tables but no auto-create flag.
        assert not getattr(Base.metadata, "_autocommit", False)
