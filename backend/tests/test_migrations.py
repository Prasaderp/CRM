from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


# Import conftest helpers (co-located in tests/)
from _testutils import alembic_cfg as _alembic_cfg, psycopg_url as _psycopg_url
from factories import make_contact, make_inquiry, make_property
from real_estate_crm.db import Base
from real_estate_crm.auth import models as auth_models
from real_estate_crm.leads import models as lead_models


# ── Helpers ────────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 7, 31, 0, 0, 0, tzinfo=timezone.utc)
_EXPIRES = _NOW + timedelta(hours=48)
_HASH_32 = hashlib.sha256(b"test").digest()  # 32 bytes


def _insert(session: Session, table_name: str, row: dict) -> None:
    session.execute(
        sa.text(f"INSERT INTO {table_name} ({', '.join(row)}) VALUES ({', '.join(':' + k for k in row)})"),
        row,
    )
    session.flush()


def _insert_raw(session: Session, table_name: str, row: dict) -> None:
    """Like _insert but passes bytes via bindparam for bytea columns."""
    cols = ", ".join(row)
    params = ", ".join(f":{k}" for k in row)
    stmt = sa.text(f"INSERT INTO {table_name} ({cols}) VALUES ({params})")
    session.execute(stmt, row)
    session.flush()


def _seed_property(session: Session, **kw) -> uuid.UUID:
    prop = make_property(**kw)
    _insert(session, "properties", prop)
    return prop["id"]


def _seed_contact(session: Session, **kw) -> uuid.UUID:
    contact = make_contact(**kw)
    _insert(session, "contacts", contact)
    return contact["id"]


def _seed_inquiry(session: Session, contact_id: uuid.UUID, property_id: uuid.UUID) -> uuid.UUID:
    inq = make_inquiry(contact_id=contact_id, property_id=property_id)
    _insert(session, "inquiries", inq)
    return inq["id"]


# ── 1. Blank-to-head upgrade ──────────────────────────────────────────────────


class TestUpgradeToHead:
    """apply_migrations (autouse session fixture) already runs upgrade; we validate state."""

    def test_all_tables_exist(self, db_session: Session) -> None:
        inspector = inspect(db_session.bind)
        tables = set(inspector.get_table_names())
        expected = {
            "properties",
            "contacts",
            "inquiries",
            "consent_records",
            "attribution_touches",
            "idempotency_requests",
            "outbox_jobs",
            "users",
            "sessions",
            "lead_status_history",
            "audit_events",
        }
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"

    def test_alembic_head_revision(self, db_session: Session) -> None:
        ctx = MigrationContext.configure(db_session.bind)
        current = ctx.get_current_heads()
        assert current == ("0002",), f"Expected head revision '0002'; got {current}"


# ── 2. Constraint and index enforcement ───────────────────────────────────────


class TestPropertyConstraints:
    def test_slug_unique_enforced(self, db_session: Session) -> None:
        _seed_property(db_session, slug="alpha-prop")
        with pytest.raises(Exception, match="unique|duplicate"):
            _seed_property(db_session, slug="alpha-prop")

    def test_slug_format_enforced(self, db_session: Session) -> None:
        bad = make_property(slug="UPPERCASE-SLUG")
        with pytest.raises(Exception):
            _insert(db_session, "properties", bad)

    def test_slug_format_leading_hyphen_rejected(self, db_session: Session) -> None:
        bad = make_property(slug="-leading-hyphen")
        with pytest.raises(Exception):
            _insert(db_session, "properties", bad)

    def test_title_length_enforced(self, db_session: Session) -> None:
        bad = make_property(title="x" * 161)
        with pytest.raises(Exception):
            _insert(db_session, "properties", bad)

    def test_valid_property_inserts(self, db_session: Session) -> None:
        pid = _seed_property(db_session, slug="valid-prop-01")
        row = db_session.execute(text("SELECT slug FROM properties WHERE id = :id"), {"id": pid}).fetchone()
        assert row is not None and row[0] == "valid-prop-01"


class TestContactConstraints:
    def test_no_contact_method_rejected(self, db_session: Session) -> None:
        bad = {
            "id": uuid.uuid4(),
            "full_name": "No Contact",
            "normalized_email": None,
            "normalized_phone": None,
        }
        with pytest.raises(Exception, match="contacts_method_ck|violates check"):
            _insert(db_session, "contacts", bad)

    def test_malformed_phone_rejected(self, db_session: Session) -> None:
        bad = {
            "id": uuid.uuid4(),
            "full_name": "Bad Phone",
            "normalized_email": None,
            "normalized_phone": "0000000000",  # not E.164
        }
        with pytest.raises(Exception, match="contacts_phone_ck|violates check"):
            _insert(db_session, "contacts", bad)

    def test_valid_phone_only_contact(self, db_session: Session) -> None:
        cid = _seed_contact(db_session, email=None, phone="+15551234567")
        row = db_session.execute(text("SELECT normalized_phone FROM contacts WHERE id = :id"), {"id": cid}).fetchone()
        assert row is not None and row[0] == "+15551234567"

    def test_partial_indexes_present(self, db_session: Session) -> None:
        inspector = inspect(db_session.bind)
        idx_names = {i["name"] for i in inspector.get_indexes("contacts")}
        assert "contacts_email_idx" in idx_names
        assert "contacts_phone_idx" in idx_names


class TestInquiryConstraints:
    def test_invalid_status_rejected(self, db_session: Session) -> None:
        pid = _seed_property(db_session)
        cid = _seed_contact(db_session)
        inq = make_inquiry(contact_id=cid, property_id=pid)
        inq["status"] = "bogus_status"
        with pytest.raises(Exception, match="inquiries_status_ck|violates check"):
            _insert(db_session, "inquiries", inq)

    def test_invalid_source_platform_rejected(self, db_session: Session) -> None:
        pid = _seed_property(db_session)
        cid = _seed_contact(db_session)
        inq = make_inquiry(contact_id=cid, property_id=pid)
        inq["source_platform"] = "myspace"
        with pytest.raises(Exception, match="inquiries_source_ck|violates check"):
            _insert(db_session, "inquiries", inq)

    def test_invalid_public_reference_rejected(self, db_session: Session) -> None:
        pid = _seed_property(db_session)
        cid = _seed_contact(db_session)
        inq = make_inquiry(contact_id=cid, property_id=pid, public_reference="bad-ref")
        with pytest.raises(Exception, match="inquiries_public_ref_ck|violates check"):
            _insert(db_session, "inquiries", inq)

    def test_version_must_be_positive(self, db_session: Session) -> None:
        pid = _seed_property(db_session)
        cid = _seed_contact(db_session)
        inq = make_inquiry(contact_id=cid, property_id=pid)
        inq["version"] = 0
        with pytest.raises(Exception, match="inquiries_version_ck|violates check"):
            _insert(db_session, "inquiries", inq)

    def test_indexes_present(self, db_session: Session) -> None:
        inspector = inspect(db_session.bind)
        idx_names = {i["name"] for i in inspector.get_indexes("inquiries")}
        assert "inquiries_submitted_idx" in idx_names
        assert "inquiries_status_idx" in idx_names
        assert "inquiries_contact_idx" in idx_names
        assert "inquiries_property_idx" in idx_names


class TestConsentRecordConstraints:
    def test_requested_contact_false_rejected(self, db_session: Session) -> None:
        pid = _seed_property(db_session)
        cid = _seed_contact(db_session)
        iid = _seed_inquiry(db_session, cid, pid)
        row = {
            "inquiry_id": iid,
            "notice_version": "v1",
            "notice_text": "Notice text",
            "notice_sha256": _HASH_32,
            "locale": "en-IN",
            "requested_contact": False,  # must be TRUE
            "capture_surface": "website",
        }
        with pytest.raises(Exception, match="consent_contact_ck|violates check"):
            _insert_raw(db_session, "consent_records", row)

    def test_short_sha256_rejected(self, db_session: Session) -> None:
        pid = _seed_property(db_session)
        cid = _seed_contact(db_session)
        iid = _seed_inquiry(db_session, cid, pid)
        row = {
            "inquiry_id": iid,
            "notice_version": "v1",
            "notice_text": "Notice text",
            "notice_sha256": b"\x00" * 16,  # 16 bytes, not 32
            "locale": "en-IN",
            "requested_contact": True,
            "capture_surface": "website",
        }
        with pytest.raises(Exception, match="consent_notice_hash_ck|violates check"):
            _insert_raw(db_session, "consent_records", row)

    def test_valid_consent_inserts(self, db_session: Session) -> None:
        pid = _seed_property(db_session)
        cid = _seed_contact(db_session)
        iid = _seed_inquiry(db_session, cid, pid)
        row = {
            "inquiry_id": iid,
            "notice_version": "2026-07-30",
            "notice_text": "By submitting you agree.",
            "notice_sha256": _HASH_32,
            "locale": "en-IN",
            "requested_contact": True,
            "capture_surface": "website",
        }
        _insert_raw(db_session, "consent_records", row)
        result = db_session.execute(
            text("SELECT notice_version FROM consent_records WHERE inquiry_id = :iid"),
            {"iid": iid},
        ).fetchone()
        assert result is not None


class TestAttributionTouchConstraints:
    def _base_touch(self, inquiry_id: uuid.UUID) -> dict:
        return {
            "id": uuid.uuid4(),
            "inquiry_id": inquiry_id,
            "landing_path": "/properties/test-prop",
        }

    def test_incomplete_click_id_pair_rejected(self, db_session: Session) -> None:
        """click_id_kind without click_id_value must fail."""
        pid = _seed_property(db_session)
        cid = _seed_contact(db_session)
        iid = _seed_inquiry(db_session, cid, pid)
        row = self._base_touch(iid)
        row["click_id_kind"] = "fbclid"
        row["click_id_value"] = None  # missing partner
        with pytest.raises(Exception, match="attribution_click_pair_ck|violates check"):
            _insert(db_session, "attribution_touches", row)

    def test_invalid_click_kind_rejected(self, db_session: Session) -> None:
        pid = _seed_property(db_session)
        cid = _seed_contact(db_session)
        iid = _seed_inquiry(db_session, cid, pid)
        row = self._base_touch(iid)
        row["click_id_kind"] = "linktrkr"
        row["click_id_value"] = "abc123"
        with pytest.raises(Exception, match="attribution_click_kind_ck|violates check"):
            _insert(db_session, "attribution_touches", row)

    def test_valid_touch_no_click(self, db_session: Session) -> None:
        pid = _seed_property(db_session)
        cid = _seed_contact(db_session)
        iid = _seed_inquiry(db_session, cid, pid)
        row = self._base_touch(iid)
        _insert(db_session, "attribution_touches", row)

    def test_duplicate_touch_type_rejected(self, db_session: Session) -> None:
        """UNIQUE (inquiry_id, touch_type) enforced."""
        pid = _seed_property(db_session)
        cid = _seed_contact(db_session)
        iid = _seed_inquiry(db_session, cid, pid)
        row1 = self._base_touch(iid)
        row2 = {**self._base_touch(iid), "id": uuid.uuid4()}
        _insert(db_session, "attribution_touches", row1)
        with pytest.raises(Exception, match="unique|duplicate|attribution_one_touch_uk"):
            _insert(db_session, "attribution_touches", row2)


class TestIdempotencyConstraints:
    def _base_idem(self) -> dict:
        return {
            "endpoint": "/api/v1/leads",
            "key": uuid.uuid4(),
            "request_sha256": _HASH_32,
            "inquiry_id": None,
            "response_status": None,
            "response_body": None,
            "created_at": _NOW,
            "expires_at": _EXPIRES,
        }

    def test_incomplete_response_rejected(self, db_session: Session) -> None:
        """Having inquiry_id without response_status must fail idempotency_complete_ck."""
        pid = _seed_property(db_session)
        cid = _seed_contact(db_session)
        iid = _seed_inquiry(db_session, cid, pid)
        row = self._base_idem()
        row["inquiry_id"] = iid
        row["response_status"] = None  # incomplete: inquiry_id set but no status/body
        row["response_body"] = None
        with pytest.raises(Exception, match="idempotency_complete_ck|violates check"):
            _insert_raw(db_session, "idempotency_requests", row)

    def test_short_hash_rejected(self, db_session: Session) -> None:
        row = self._base_idem()
        row["request_sha256"] = b"\x00" * 10
        with pytest.raises(Exception, match="idempotency_hash_ck|violates check"):
            _insert_raw(db_session, "idempotency_requests", row)

    def test_expiry_before_created_rejected(self, db_session: Session) -> None:
        row = self._base_idem()
        row["expires_at"] = _NOW - timedelta(seconds=1)
        with pytest.raises(Exception, match="idempotency_expiry_ck|violates check"):
            _insert_raw(db_session, "idempotency_requests", row)

    def test_valid_pending_row_inserts(self, db_session: Session) -> None:
        row = self._base_idem()
        _insert_raw(db_session, "idempotency_requests", row)

    def test_expiry_index_present(self, db_session: Session) -> None:
        inspector = inspect(db_session.bind)
        idx_names = {i["name"] for i in inspector.get_indexes("idempotency_requests")}
        assert "idempotency_expiry_idx" in idx_names


class TestOutboxJobConstraints:
    def _base_outbox(self) -> dict:
        return {
            "id": uuid.uuid4(),
            "job_kind": "lead_email",
            "aggregate_id": uuid.uuid4(),
            "dedupe_key": f"lead_email:{uuid.uuid4()}",
            "payload": '{"inquiry_id": "00000000-0000-4000-8000-000000000001"}',
            "state": "pending",
            "attempts": 0,
        }

    def test_invalid_state_rejected(self, db_session: Session) -> None:
        row = self._base_outbox()
        row["state"] = "queued"
        with pytest.raises(Exception, match="outbox_state_ck|violates check"):
            _insert(db_session, "outbox_jobs", row)

    def test_invalid_kind_rejected(self, db_session: Session) -> None:
        row = self._base_outbox()
        row["job_kind"] = "sms_alert"
        with pytest.raises(Exception, match="outbox_kind_ck|violates check"):
            _insert(db_session, "outbox_jobs", row)

    def test_lock_pair_kind_locked_by_without_at_rejected(self, db_session: Session) -> None:
        row = self._base_outbox()
        row["locked_by"] = "worker-01"
        row["locked_at"] = None  # pair must both be NULL or both NOT NULL
        with pytest.raises(Exception, match="outbox_lock_pair_ck|violates check"):
            _insert(db_session, "outbox_jobs", row)

    def test_completed_without_completed_at_rejected(self, db_session: Session) -> None:
        """state='completed' requires completed_at IS NOT NULL."""
        row = self._base_outbox()
        row["state"] = "completed"
        row["completed_at"] = None
        with pytest.raises(Exception, match="outbox_completion_ck|violates check"):
            _insert(db_session, "outbox_jobs", row)

    def test_dedupe_key_unique_enforced(self, db_session: Session) -> None:
        key = f"lead_email:{uuid.uuid4()}"
        row1 = self._base_outbox()
        row1["dedupe_key"] = key
        row2 = self._base_outbox()
        row2["dedupe_key"] = key
        _insert(db_session, "outbox_jobs", row1)
        with pytest.raises(Exception, match="unique|duplicate|outbox_jobs_dedupe_key_key"):
            _insert(db_session, "outbox_jobs", row2)

    def test_valid_pending_job_inserts(self, db_session: Session) -> None:
        row = self._base_outbox()
        _insert(db_session, "outbox_jobs", row)

    def test_due_and_stale_indexes_present(self, db_session: Session) -> None:
        inspector = inspect(db_session.bind)
        idx_names = {i["name"] for i in inspector.get_indexes("outbox_jobs")}
        assert "outbox_due_idx" in idx_names
        assert "outbox_stale_idx" in idx_names


# ── 3. ORM metadata drift check ───────────────────────────────────────────────


class TestAdminAuthConstraints:
    @staticmethod
    def _user(**changes: object) -> dict[str, object]:
        return {
            "id": uuid.uuid4(),
            "normalized_email": f"{uuid.uuid4().hex}@example.com",
            "display_name": "Test User",
            "password_hash": "$argon2id$synthetic-test-hash",
            "role": "admin",
            **changes,
        }

    def test_closed_role_and_session_hash_constraints(self, db_session: Session) -> None:
        with pytest.raises(Exception, match="users_role_ck|violates check"):
            _insert(db_session, "users", self._user(role="owner"))
        db_session.rollback()
        user = self._user()
        _insert(db_session, "users", user)
        with pytest.raises(Exception, match="sessions_token_hash_ck|violates check"):
            _insert(
                db_session,
                "sessions",
                {
                    "id": uuid.uuid4(),
                    "user_id": user["id"],
                    "token_sha256": b"short",
                    "csrf_sha256": _HASH_32,
                    "idle_expires_at": _NOW + timedelta(minutes=30),
                    "absolute_expires_at": _NOW + timedelta(hours=12),
                },
            )

    def test_assignee_delete_sets_null_without_deleting_inquiry(self, db_session: Session) -> None:
        user = self._user()
        _insert(db_session, "users", user)
        property_id, contact_id = _seed_property(db_session), _seed_contact(db_session)
        inquiry_id = _seed_inquiry(db_session, contact_id, property_id)
        db_session.execute(
            text("UPDATE inquiries SET assigned_user_id = :uid WHERE id = :iid"),
            {"uid": user["id"], "iid": inquiry_id},
        )
        db_session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user["id"]})
        assert db_session.scalar(
            text("SELECT assigned_user_id FROM inquiries WHERE id = :iid"), {"iid": inquiry_id}
        ) is None

    def test_auth_indexes_present(self, db_session: Session) -> None:
        inspector = inspect(db_session.bind)
        assert "sessions_user_active_idx" in {index["name"] for index in inspector.get_indexes("sessions")}
        assert "inquiries_assignee_idx" in {index["name"] for index in inspector.get_indexes("inquiries")}
        assert "audit_entity_idx" in {index["name"] for index in inspector.get_indexes("audit_events")}


class TestMetadataDrift:
    """
    Verify that the SQLAlchemy ORM models define no tables that differ from the
    live schema after migration. This catches drift between Phase 4 models and
    the Phase 5 migration.
    """

    def test_metadata_has_no_pending_migration_operations(self, db_session: Session) -> None:
        assert lead_models.Property.__table__ is Base.metadata.tables["properties"]
        assert auth_models.User.__table__ is Base.metadata.tables["users"]
        context = MigrationContext.configure(
            db_session.connection(),
            opts={"compare_type": True, "compare_server_default": True},
        )
        assert compare_metadata(context, Base.metadata) == []

    def test_all_orm_tables_exist_in_db(self, db_session: Session) -> None:
        inspector = inspect(db_session.bind)
        live_tables = set(inspector.get_table_names())
        # Exclude users/sessions/etc. (Phase 20) — not yet created.
        phase5_tables = {
            "properties",
            "contacts",
            "inquiries",
            "consent_records",
            "attribution_touches",
            "idempotency_requests",
            "outbox_jobs",
        }
        missing = phase5_tables - live_tables
        assert not missing, f"ORM tables missing from live schema: {missing}"

    def test_inquiries_columns_match(self, db_session: Session) -> None:
        inspector = inspect(db_session.bind)
        live_cols = {c["name"] for c in inspector.get_columns("inquiries")}
        expected = {
            "id",
            "public_reference",
            "contact_id",
            "property_id",
            "source_platform",
            "capture_surface",
            "form_version",
            "intent",
            "budget_band",
            "timeframe",
            "preferred_contact_method",
            "message",
            "status",
            "dedupe_state",
            "version",
            "submitted_at",
            "updated_at",
            "assigned_user_id",
        }
        assert expected.issubset(live_cols), f"Missing columns: {expected - live_cols}"

    def test_outbox_jobs_columns_match(self, db_session: Session) -> None:
        inspector = inspect(db_session.bind)
        live_cols = {c["name"] for c in inspector.get_columns("outbox_jobs")}
        expected = {
            "id",
            "job_kind",
            "aggregate_id",
            "dedupe_key",
            "payload",
            "state",
            "attempts",
            "available_at",
            "locked_by",
            "locked_at",
            "last_error_code",
            "smtp_message_id",
            "created_at",
            "completed_at",
        }
        assert expected.issubset(live_cols), f"Missing columns: {expected - live_cols}"


# ── 4. Downgrade → head round-trip ────────────────────────────────────────────


class TestDowngradeUpgradeRoundTrip:
    """
    Proves 0002 is additive, its downgrade preserves 0001 data, and a full
    downgrade/upgrade restores the exact schema.

    IMPORTANT: This test mutates schema state and uses its own dedicated connection
    (NOT the per-test db_session) because SAVEPOINTs cannot wrap DDL on PostgreSQL.
    It runs last to avoid interfering with other tests.
    """

    def test_round_trip(self, test_db_url: str) -> None:
        cfg = _alembic_cfg(test_db_url)
        alembic_command.downgrade(cfg, "base")
        engine = sa.create_engine(_psycopg_url(test_db_url), future=True)
        alembic_command.upgrade(cfg, "0001")
        property_row, contact_row = make_property(slug="migration-preserved"), make_contact()
        inquiry_row = make_inquiry(contact_id=contact_row["id"], property_id=property_row["id"])
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO properties (id, slug, title, summary, locality) "
                    "VALUES (:id, :slug, :title, :summary, :locality)"
                ),
                property_row,
            )
            connection.execute(
                text(
                    "INSERT INTO contacts (id, full_name, normalized_email, normalized_phone) "
                    "VALUES (:id, :full_name, :normalized_email, :normalized_phone)"
                ),
                contact_row,
            )
            connection.execute(
                text(
                    "INSERT INTO inquiries "
                    "(id, public_reference, contact_id, property_id, source_platform, form_version) "
                    "VALUES (:id, :public_reference, :contact_id, :property_id, :source_platform, :form_version)"
                ),
                inquiry_row,
            )

        alembic_command.upgrade(cfg, "head")
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT count(*) FROM inquiries WHERE id = :id"), {"id": inquiry_row["id"]}
            ) == 1
            assert connection.scalar(
                text("SELECT assigned_user_id FROM inquiries WHERE id = :id"), {"id": inquiry_row["id"]}
            ) is None

        alembic_command.downgrade(cfg, "0001")
        with engine.connect() as connection:
            inspector = inspect(connection)
            assert "users" not in inspector.get_table_names()
            assert "assigned_user_id" not in {column["name"] for column in inspector.get_columns("inquiries")}
            assert connection.scalar(
                text("SELECT count(*) FROM inquiries WHERE id = :id"), {"id": inquiry_row["id"]}
            ) == 1

        alembic_command.downgrade(cfg, "base")
        with engine.connect() as conn:
            inspector = inspect(conn)
            remaining = {
                t
                for t in inspector.get_table_names()
                if t
                in {
                    "properties",
                    "contacts",
                    "inquiries",
                    "consent_records",
                    "attribution_touches",
                    "idempotency_requests",
                    "outbox_jobs",
                    "users",
                    "sessions",
                    "lead_status_history",
                    "audit_events",
                }
            }
            assert not remaining, f"Tables not dropped by downgrade: {remaining}"
        alembic_command.upgrade(cfg, "head")

        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            heads = ctx.get_current_heads()
            assert heads == ("0002",), f"Expected head '0002' after re-upgrade, got {heads}"

        engine.dispose()
