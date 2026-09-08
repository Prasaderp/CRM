from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from real_estate_crm.admin.service import InquiryNotFound, InquiryPage, StaleInquiryVersion
from real_estate_crm.app import create_app
from real_estate_crm.auth.models import AuditEvent, User
from real_estate_crm.auth.service import AuthenticatedSession, hash_password
from real_estate_crm.config import get_settings
from real_estate_crm.leads.models import Contact, Inquiry, Property
from real_estate_crm.leads.routes import LeadRateLimiter

NOW = datetime(2026, 7, 31, tzinfo=timezone.utc)
INQUIRY_ID = uuid.UUID("30000000-0000-4000-8000-000000000024")
USER_ID = uuid.UUID("20000000-0000-4000-8000-000000000024")


def _detail(*, status: str = "new", version: int = 1) -> dict[str, object]:
    return {
        "id": str(INQUIRY_ID),
        "reference": "RE-API0000024",
        "status": status,
        "version": version,
        "sourcePlatform": "direct",
        "intent": "information",
        "submittedAt": NOW.isoformat(),
        "contact": {"fullName": "Synthetic Lead", "email": "lead@example.com", "phone": None},
        "property": {"id": str(uuid.uuid4()), "title": "API Residence"},
        "assignee": None,
        "captureSurface": "website",
        "formVersion": "property-inquiry-1.0",
        "budgetBand": None,
        "timeframe": None,
        "preferredContactMethod": "email",
        "message": "Synthetic inquiry",
        "dedupeState": "clear",
        "updatedAt": NOW.isoformat(),
        "consent": {
            "noticeVersion": "2026-07-30",
            "requestedContact": True,
            "marketing": False,
            "adMeasurement": False,
            "recordedAt": NOW.isoformat(),
        },
        "statusHistory": [],
    }


class FakeAuth:
    role = "agent"

    def lookup_session(self, token: str, *, refresh: bool = True) -> AuthenticatedSession | None:
        if token != "valid-session":
            return None
        return AuthenticatedSession(
            uuid.uuid4(),
            USER_ID,
            "agent@example.com",
            "API Agent",
            self.role,
            b"csrf",
            NOW + timedelta(minutes=30),
            NOW + timedelta(hours=12),
        )

    def verify_csrf(self, _session: AuthenticatedSession, token: str) -> bool:
        return token == "valid-csrf"


class FakeAdmin:
    failure: Exception | None = None
    last_filters: object | None = None

    def list_inquiries(self, *, page_size: int, cursor: str | None, filters: object) -> InquiryPage:
        if self.failure:
            raise self.failure
        self.last_filters = filters
        detail = _detail()
        return InquiryPage(
            [
                {
                    key: detail[key]
                    for key in (
                        "id",
                        "reference",
                        "status",
                        "version",
                        "sourcePlatform",
                        "intent",
                        "submittedAt",
                        "contact",
                        "property",
                        "assignee",
                    )
                }
            ],
            "next-cursor",
        )

    def get_inquiry(self, inquiry_id: uuid.UUID) -> dict[str, object]:
        if self.failure:
            raise self.failure
        if inquiry_id != INQUIRY_ID:
            raise InquiryNotFound
        return _detail()

    def list_active_users(self) -> list[dict[str, str]]:
        if self.failure:
            raise self.failure
        return [{"id": str(USER_ID), "displayName": "API Agent", "role": "agent"}]

    def update_status(self, inquiry_id: uuid.UUID, **values: object) -> dict[str, object]:
        if self.failure:
            raise self.failure
        result = _detail(status=str(values["status"]), version=int(values["expected_version"]) + 1)
        result["statusHistory"] = [
            {
                "id": str(uuid.uuid4()),
                "fromStatus": "new",
                "toStatus": values["status"],
                "createdAt": NOW.isoformat(),
                "actor": {"id": str(values["actor_user_id"]), "displayName": "API Agent"},
            }
        ]
        return result

    def update_assignment(self, inquiry_id: uuid.UUID, **values: object) -> dict[str, object]:
        if self.failure:
            raise self.failure
        return _detail(version=int(values["expected_version"]) + 1)


class FakeLead:
    def get_property(self, _slug: str) -> None:
        return None


def _client() -> tuple[TestClient, FakeAuth, FakeAdmin]:
    auth, admin = FakeAuth(), FakeAdmin()
    settings = get_settings().model_copy(
        update={"environment": "local", "public_origin": "http://testserver", "trusted_origins_raw": ""}
    )
    app = create_app(
        settings=settings,
        session_factory=sessionmaker(class_=Session),
        rate_limiter=LeadRateLimiter(),
        service_factory=lambda _sessions, _settings: FakeLead(),  # type: ignore[arg-type,return-value]
        auth_service_factory=lambda _sessions: auth,  # type: ignore[arg-type,return-value]
        admin_service_factory=lambda _sessions: admin,  # type: ignore[arg-type,return-value]
    )
    client = TestClient(app, raise_server_exceptions=False)
    return client, auth, admin


def _authenticate(client: TestClient) -> None:
    client.cookies.set("session_id", "valid-session")
    client.cookies.set("csrf_token", "valid-csrf")


def test_crm_list_detail_users_filters_and_pii_boundary() -> None:
    client, _, admin = _client()
    _authenticate(client)
    listed = client.get(
        "/api/v1/inquiries",
        params={"pageSize": 1, "status": "new", "propertyId": str(uuid.uuid4()), "sort": "DROP TABLE users"},
    )
    detail = client.get(f"/api/v1/inquiries/{INQUIRY_ID}")
    users = client.get("/api/v1/users")
    assert listed.status_code == detail.status_code == users.status_code == 200
    assert listed.json()["items"][0]["contact"]["email"] == "lead@example.com"
    assert detail.json()["consent"]["noticeVersion"] == "2026-07-30"
    assert users.json() == [{"id": str(USER_ID), "displayName": "API Agent", "role": "agent"}]
    assert admin.last_filters is not None
    for response in (listed, detail, users):
        assert response.headers["cache-control"] == "private, no-store"


def test_auth_and_wrong_role_hide_resource_existence() -> None:
    client, auth, _ = _client()
    paths = [f"/api/v1/inquiries/{INQUIRY_ID}", f"/api/v1/inquiries/{uuid.uuid4()}"]
    assert [client.get(path).status_code for path in paths] == [401, 401]
    _authenticate(client)
    auth.role = "viewer"
    responses = [client.get(path) for path in paths]
    assert [response.status_code for response in responses] == [403, 403]
    assert responses[0].json()["error"] == responses[1].json()["error"]


def test_mutations_require_bound_csrf_and_return_audit_visible_result() -> None:
    client, _, _ = _client()
    _authenticate(client)
    payload = {"status": "contacted", "expectedVersion": 1}
    missing = client.patch(
        f"/api/v1/inquiries/{INQUIRY_ID}/status",
        json=payload,
        headers={"Origin": "http://testserver"},
    )
    mismatch = client.patch(
        f"/api/v1/inquiries/{INQUIRY_ID}/status",
        json=payload,
        headers={"Origin": "http://testserver", "X-CSRF-Token": "wrong"},
    )
    changed = client.patch(
        f"/api/v1/inquiries/{INQUIRY_ID}/status",
        json=payload,
        headers={"Origin": "http://testserver", "X-CSRF-Token": "valid-csrf"},
    )
    assert missing.status_code == mismatch.status_code == 403
    assert changed.status_code == 200
    body = changed.json()
    assert (body["status"], body["version"]) == ("contacted", 2)
    assert body["statusHistory"][0]["toStatus"] == "contacted"


def test_conflict_malformed_contract_and_database_outage_are_sanitized() -> None:
    client, _, admin = _client()
    _authenticate(client)
    headers = {"Origin": "http://testserver", "X-CSRF-Token": "valid-csrf"}
    admin.failure = StaleInquiryVersion()
    conflict = client.patch(
        f"/api/v1/inquiries/{INQUIRY_ID}/status",
        json={"status": "won", "expectedVersion": 1},
        headers=headers,
    )
    admin.failure = sa.exc.OperationalError("SELECT secret", {}, ConnectionError("database-password"))
    outage = client.get("/api/v1/inquiries")
    malformed = client.patch(
        f"/api/v1/inquiries/{INQUIRY_ID}/assignment",
        json={"assignedUserId": "not-a-uuid", "expectedVersion": 1, "email": "leak@example.com"},
        headers=headers,
    )
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "stale_version"
    assert b"crm_stale_version_conflicts_total 1.0" in client.app.state.metrics.render()
    assert outage.status_code == 503 and "database-password" not in outage.text and "SELECT secret" not in outage.text
    assert malformed.status_code == 422 and "leak@example.com" not in malformed.text


def test_real_login_to_atomic_crm_mutation_flow(db_session: Session) -> None:
    user = User(
        id=uuid.uuid4(),
        normalized_email=f"workflow-{uuid.uuid4().hex}@example.com",
        display_name="Workflow Agent",
        password_hash=hash_password("correct horse battery"),
        role="agent",
    )
    prop = Property(
        id=uuid.uuid4(),
        slug=f"workflow-{uuid.uuid4().hex[:12]}",
        title="Workflow Residence",
        summary="Synthetic",
        locality="Test City",
    )
    contact = Contact(id=uuid.uuid4(), full_name="Workflow Lead", normalized_email="workflow-lead@example.com")
    inquiry = Inquiry(
        id=uuid.uuid4(),
        public_reference=f"RE-{uuid.uuid4().hex[:10].upper()}",
        contact=contact,
        property=prop,
        source_platform="direct",
        form_version="property-inquiry-1.0",
        status="new",
    )
    db_session.add_all([user, inquiry])
    db_session.flush()
    settings = get_settings().model_copy(
        update={"environment": "local", "public_origin": "http://testserver", "trusted_origins_raw": ""}
    )
    app = create_app(
        settings=settings,
        session_factory=sessionmaker(bind=db_session.connection(), expire_on_commit=False),
        rate_limiter=LeadRateLimiter(),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": user.normalized_email, "password": "correct horse battery"},
            headers={"Origin": "http://testserver"},
        )
        assert login.status_code == 200
        listed = client.get("/api/v1/inquiries", params={"propertyId": str(prop.id)})
        assert listed.status_code == 200 and [item["id"] for item in listed.json()["items"]] == [str(inquiry.id)]
        changed = client.patch(
            f"/api/v1/inquiries/{inquiry.id}/status",
            json={"status": "qualified", "expectedVersion": 1},
            headers={"Origin": "http://testserver", "X-CSRF-Token": client.cookies["csrf_token"]},
        )
        assert changed.status_code == 200
        assert (changed.json()["status"], changed.json()["version"]) == ("qualified", 2)
        assert changed.json()["statusHistory"][0]["toStatus"] == "qualified"
    db_session.expire_all()
    audit = db_session.scalar(sa.select(AuditEvent).where(AuditEvent.entity_id == inquiry.id))
    assert audit and audit.action == "inquiry.status.changed" and audit.actor_user_id == user.id
