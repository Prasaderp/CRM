from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from real_estate_crm.app import app

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "frontend" / "src" / "api" / "openapi.json"
EXPORTER = ROOT / "backend" / "scripts" / "export_openapi.py"
EXPECTED_OPERATIONS = {
    ("/api/v1/auth/login", "post"): "login",
    ("/api/v1/auth/logout", "post"): "logout",
    ("/api/v1/auth/session", "get"): "getSession",
    ("/api/v1/inquiries", "get"): "listInquiries",
    ("/api/v1/inquiries/{inquiry_id}", "get"): "getInquiry",
    ("/api/v1/inquiries/{inquiry_id}/assignment", "patch"): "updateInquiryAssignment",
    ("/api/v1/inquiries/{inquiry_id}/status", "patch"): "updateInquiryStatus",
    ("/api/v1/leads", "post"): "createLead",
    ("/api/v1/properties/{slug}", "get"): "getProperty",
    ("/api/v1/users", "get"): "listAssignees",
}
FORBIDDEN_FRAGMENTS = {
    "password_hash",
    "secret",
    "token_sha256",
    "normalized_email",
    "normalized_phone",
    "notice_text",
    "notice_sha256",
    "locked_by",
    "dedupe_key",
    "smtp",
    "database_url",
}


def _exporter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_openapi", EXPORTER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_contract_is_canonical_and_reproducible(tmp_path: Path) -> None:
    exporter = _exporter()
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    assert exporter.export_openapi(first) and exporter.export_openapi(second)
    assert first.read_bytes() == second.read_bytes() == ARTIFACT.read_bytes()
    assert exporter.export_openapi(ARTIFACT, check=True)


def test_only_expected_operations_are_exposed_with_stable_ids() -> None:
    schema = app.openapi()
    operations = {
        (path, method): operation["operationId"]
        for path, path_item in schema["paths"].items()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert operations == EXPECTED_OPERATIONS
    assert len(operations.values()) == len(set(operations.values()))
    assert set(schema["paths"]["/api/v1/leads"]["post"]["responses"]) >= {"201", "422"}
    assert set(schema["paths"]["/api/v1/properties/{slug}"]["get"]["responses"]) >= {"200", "422"}
    assert set(schema["paths"]["/api/v1/auth/login"]["post"]["responses"]) >= {"200", "422"}
    assert set(schema["paths"]["/api/v1/inquiries"]["get"]["responses"]) >= {"200", "422"}
    for suffix in ("status", "assignment"):
        mutation = schema["paths"][f"/api/v1/inquiries/{{inquiry_id}}/{suffix}"]["patch"]
        assert set(mutation["responses"]) >= {"200", "401", "403", "404", "409", "422"}
    for path, path_item in schema["paths"].items():
        if not path.startswith("/api/v1/"):
            continue
        for method, operation in path_item.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                assert all(
                    {"Cache-Control", "X-Request-ID"} <= set(response["headers"])
                    for response in operation["responses"].values()
                )


def test_api_models_are_closed_and_internal_fields_never_escape() -> None:
    schema: dict[str, Any] = app.openapi()
    components = schema["components"]["schemas"]
    api_models = {
        "AssigneeChoice",
        "AssignmentMutation",
        "AttributionInput",
        "ContactResponse",
        "ConsentInput",
        "ConsentSummary",
        "ContactInput",
        "InquiryDetail",
        "InquiryInput",
        "InquiryPageResponse",
        "InquirySummary",
        "HistoryActor",
        "LeadAccepted",
        "LeadRequest",
        "LoginRequest",
        "PropertySummary",
        "PropertyResponse",
        "SessionResponse",
        "StatusHistoryItem",
        "StatusMutation",
        "UserSummary",
    }
    assert api_models <= components.keys()
    assert all(components[name].get("additionalProperties") is False for name in api_models)
    serialized = json.dumps(schema, sort_keys=True).lower()
    assert not (FORBIDDEN_FRAGMENTS & set(serialized.replace('"', " ").replace(":", " ").split()))
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in serialized


def test_contract_generation_requires_no_database_io(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import sqlalchemy.engine

    monkeypatch.setattr(sqlalchemy.engine.Engine, "connect", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError))
    app.openapi_schema = None
    assert app.openapi()["openapi"].startswith("3.")
