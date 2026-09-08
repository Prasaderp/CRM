from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: Literal["local", "production", "test"] = "local"
    database_url: PostgresDsn = Field(repr=False)
    test_database_url: PostgresDsn | None = Field(default=None, repr=False)
    public_origin: HttpUrl
    trusted_origins_raw: str = Field(default="", alias="trusted_origins")
    canonical_notice_version: str = Field(min_length=1, max_length=40)
    canonical_notice_text: str = Field(min_length=1, max_length=8000)
    max_request_body_size_bytes: int = Field(default=16 * 1024, ge=1024, le=16 * 1024)
    idempotency_expiry_hours: Literal[48] = 48
    session_cookie_name: str = "session_id"
    csrf_cookie_name: str = "csrf_token"
    secure_cookies: bool = True
    session_refresh_min_interval_seconds: int = Field(default=300, ge=300)
    smtp_host: str = Field(min_length=1)
    smtp_port: int = Field(ge=1, le=65535)
    smtp_security: Literal["starttls", "tls", "none"] = "starttls"
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_sender: str = Field(min_length=3, max_length=254)
    recipient_allow_list_raw: str = Field(alias="recipient_allow_list")
    worker_claim_limit: int = Field(default=20, ge=1, le=100)
    worker_lease_seconds: int = Field(default=120, ge=30, le=600)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        populate_by_name=True,
    )

    @property
    def trusted_origins(self) -> tuple[str, ...]:
        return tuple(value.strip() for value in self.trusted_origins_raw.split(",") if value.strip())

    @property
    def recipient_allow_list(self) -> tuple[str, ...]:
        return tuple(value.strip() for value in self.recipient_allow_list_raw.split(",") if value.strip())

    @model_validator(mode="after")
    def validate_security_boundary(self) -> Settings:
        if not self.canonical_notice_text.strip():
            raise ValueError("canonical_notice_text cannot be blank")
        if not self.recipient_allow_list:
            raise ValueError("recipient_allow_list cannot be empty")
        if self.environment != "local":
            if not self.secure_cookies:
                raise ValueError("secure_cookies must be true outside local environment")
            if self.public_origin.scheme != "https":
                raise ValueError("public_origin must use HTTPS outside local environment")
            if not self.trusted_origins:
                raise ValueError("trusted_origins must be configured outside local environment")
            if self.smtp_username is None or self.smtp_password is None:
                raise ValueError("SMTP authentication is required outside local environment")
            if self.smtp_security == "none":
                raise ValueError("smtp_security must be starttls or tls outside local environment")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
