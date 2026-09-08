from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from real_estate_crm.config import Settings


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "local",
        "database_url": "postgresql://user:database-secret@localhost/db",
        "public_origin": "http://localhost:5173",
        "canonical_notice_version": "v1",
        "canonical_notice_text": "Notice",
        "smtp_host": "localhost",
        "smtp_port": 1025,
        "smtp_sender": "test@example.com",
        "recipient_allow_list": "admin@example.com,sales@example.com",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_valid_local_settings() -> None:
    settings = _settings()
    assert settings.recipient_allow_list == ("admin@example.com", "sales@example.com")
    assert settings.idempotency_expiry_hours == 48
    assert settings.max_request_body_size_bytes == 16 * 1024


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("canonical_notice_text", "  ", "cannot be blank"),
        ("recipient_allow_list", "", "cannot be empty"),
        ("max_request_body_size_bytes", 16 * 1024 + 1, "less than or equal"),
        ("idempotency_expiry_hours", 24, "Input should be 48"),
        ("session_refresh_min_interval_seconds", 299, "greater than or equal"),
    ],
)
def test_fail_closed_bounds(field: str, value: object, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _settings(**{field: value})


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"secure_cookies": False}, "secure_cookies must be true"),
        ({"public_origin": "http://example.com"}, "public_origin must use HTTPS"),
        ({"trusted_origins": ""}, "trusted_origins must be configured"),
        ({"smtp_username": None, "smtp_password": None}, "SMTP authentication is required"),
    ],
)
def test_production_security_gates(overrides: dict[str, object], message: str) -> None:
    production: dict[str, object] = {
        "environment": "production",
        "public_origin": "https://example.com",
        "trusted_origins": "https://example.com",
        "secure_cookies": True,
        "smtp_username": "user",
        "smtp_password": "smtp-secret",
    }
    production.update(overrides)
    with pytest.raises(ValidationError, match=message):
        _settings(**production)


def test_rejects_unknown_configuration() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _settings(typoed_security_flag=True)


def test_secret_values_are_redacted_from_repr() -> None:
    rendered = repr(_settings(smtp_password="smtp-secret"))
    assert "smtp-secret" not in rendered
    assert "database-secret" not in rendered
