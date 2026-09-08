from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from real_estate_crm.app import create_app
from real_estate_crm.config import get_settings
from real_estate_crm.db import DatabaseError
from real_estate_crm.leads.routes import LeadRateLimiter
from real_estate_crm.leads.schemas import LeadAccepted
from real_estate_crm.leads.service import IdempotencyConflict, PropertyNotFound


def _payload() -> dict[str, object]:
    return {
        "propertySlug": "route-test-home",
        "formVersion": "property-inquiry-1.0",
        "contact": {"fullName": "Route Tester", "email": "route@example.com"},
        "inquiry": {"intent": "information"},
        "consent": {
            "privacyNoticeVersion": "client-assertion",
            "requestedContact": True,
            "marketing": False,
            "adMeasurement": False,
        },
    }


class FakeService:
    failure: Exception | None = None
    accepted = LeadAccepted.model_validate(
        {
            "inquiryId": "00000000-0000-4000-8000-000000000001",
            "reference": "RE-AAAAAAAAAA",
            "status": "new",
            "submittedAt": datetime(2026, 7, 31, tzinfo=timezone.utc),
        }
    )

    def accept(self, _lead, _key):  # type: ignore[no-untyped-def]
        if self.failure:
            raise self.failure
        return self.accepted, False

    def get_property(self, slug: str):  # type: ignore[no-untyped-def]
        if slug != "route-test-home" or isinstance(self.failure, PropertyNotFound):
            return None
        return SimpleNamespace(
            slug=slug,
            title="Route Test Home",
            summary="Synthetic",
            locality="Test City",
            price_label=None,
            project_registration_number=None,
            registration_authority_url=None,
        )


@pytest.fixture
def fake() -> FakeService:
    return FakeService()


@pytest.fixture
def client(fake: FakeService) -> TestClient:
    app = create_app(
        settings=get_settings(),
        session_factory=sessionmaker(class_=Session),
        rate_limiter=LeadRateLimiter(),
        service_factory=lambda _sessions, _settings: fake,  # type: ignore[arg-type,return-value]
    )
    return TestClient(app, raise_server_exceptions=False)


def _post(client: TestClient, payload: object | None = None, *, key: str | None = None, **kwargs):  # type: ignore[no-untyped-def]
    headers = {"Content-Type": "application/json", "Idempotency-Key": key or str(uuid.uuid4())}
    headers.update(kwargs.pop("headers", {}))
    return client.post("/api/v1/leads", content=json.dumps(_payload() if payload is None else payload), headers=headers, **kwargs)


def test_public_property_and_lead_contract(client: TestClient) -> None:
    prop = client.get("/api/v1/properties/route-test-home")
    response = _post(client)
    assert prop.status_code == 200 and prop.json()["title"] == "Route Test Home"
    assert response.status_code == 201 and response.json()["reference"] == "RE-AAAAAAAAAA"
    for result in (prop, response):
        assert result.headers["cache-control"] == "private, no-store"
        uuid.UUID(result.headers["x-request-id"])
    assert "normalized_email" not in prop.text and "notice" not in response.text


@pytest.mark.parametrize(
    ("content", "headers", "status", "code"),
    [
        (b"{", {"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())}, 400, "malformed_json"),
        (b"{}", {"Content-Type": "text/plain", "Idempotency-Key": str(uuid.uuid4())}, 415, "unsupported_media_type"),
        (
            json.dumps(_payload()).encode(),
            {"Content-Type": "application/json", "Idempotency-Key": "not-a-uuid"},
            400,
            "invalid_idempotency_key",
        ),
        (
            json.dumps(_payload()).encode(),
            {"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid1())},
            400,
            "invalid_idempotency_key",
        ),
        (
            json.dumps({**_payload(), "unknown": True}).encode(),
            {"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())},
            422,
            "validation_failed",
        ),
    ],
)
def test_malformed_requests_are_sanitized(
    client: TestClient, content: bytes, headers: dict[str, str], status: int, code: str
) -> None:
    response = client.post("/api/v1/leads", content=content, headers=headers)
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert "traceback" not in response.text.lower() and "route@example.com" not in response.text


def test_body_limit_honeypot_and_rate_limit(client: TestClient) -> None:
    oversized = client.post(
        "/api/v1/leads",
        content=b"x" * (16 * 1024 + 1),
        headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())},
    )
    trapped = _post(client, {**_payload(), "website": "https://bot.invalid"})
    assert oversized.status_code == 413 and trapped.status_code == 422
    fresh = TestClient(
        create_app(
            settings=get_settings(),
            session_factory=sessionmaker(class_=Session),
            rate_limiter=LeadRateLimiter(),
            service_factory=lambda _sessions, _settings: FakeService(),  # type: ignore[arg-type,return-value]
        ),
        raise_server_exceptions=False,
    )
    responses = [_post(fresh) for _ in range(6)]
    assert [result.status_code for result in responses] == [201, 201, 201, 201, 201, 429]
    assert responses[-1].headers["retry-after"] == "60"


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (IdempotencyConflict(), 409, "idempotency_conflict"),
        (PropertyNotFound(), 404, "property_not_found"),
        (DatabaseError("contains database host and credentials"), 503, "service_unavailable"),
        (RuntimeError("secret internal state"), 500, "internal_error"),
    ],
)
def test_domain_and_infrastructure_errors_do_not_leak(
    client: TestClient, fake: FakeService, failure: Exception, status: int, code: str
) -> None:
    fake.failure = failure
    response = _post(client)
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert not str(failure) or str(failure) not in response.text
