from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import unicodedata
from urllib.parse import SplitResult, urlsplit

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict

from real_estate_crm.leads.schemas import (
    AttributionInput,
    BudgetBand,
    ClickIdKind,
    InquiryIntent,
    LeadRequest,
    PreferredContactMethod,
    Timeframe,
)


class NormalizedAttribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    utm_source: str | None
    utm_medium: str | None
    utm_campaign: str | None
    utm_content: str | None
    utm_term: str | None
    click_id_kind: ClickIdKind | None
    click_id_value: str | None
    landing_path: str
    referrer_origin_path: str | None


class NormalizedLead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    property_slug: str
    form_version: str
    full_name: str
    email: str | None
    phone: str | None
    preferred_contact_method: PreferredContactMethod | None
    intent: InquiryIntent | None
    budget_band: BudgetBand | None
    timeframe: Timeframe | None
    message: str | None
    notice_version_assertion: str
    requested_contact: bool
    marketing_opt_in: bool
    ad_measurement_opt_in: bool
    locale: str
    attribution: NormalizedAttribution


def _normalize_whitespace(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()


def normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return validate_email(value, check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise ValueError("email is not syntactically valid") from exc


def _safe_host(parts: SplitResult) -> str:
    if parts.username is not None or parts.password is not None:
        raise ValueError("URL credentials are not allowed")
    try:
        hostname, port = parts.hostname, parts.port
    except ValueError as exc:
        raise ValueError("URL port is invalid") from exc
    if hostname is None:
        raise ValueError("absolute URL requires a host")
    try:
        host = str(ipaddress.ip_address(hostname))
        if ":" in host:
            host = f"[{host}]"
    except ValueError:
        try:
            host = hostname.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError("URL host is invalid") from exc
    default_port = (parts.scheme.lower() == "http" and port == 80) or (parts.scheme.lower() == "https" and port == 443)
    return host if port is None or default_port else f"{host}:{port}"


def sanitize_origin_path(value: str, *, field: str) -> str:
    parts = urlsplit(value)
    if parts.scheme:
        scheme = parts.scheme.lower()
        if scheme not in {"http", "https"}:
            raise ValueError(f"{field} must use http or https")
        origin = f"{scheme}://{_safe_host(parts)}"
    else:
        if parts.netloc or not parts.path.startswith("/"):
            raise ValueError(f"{field} must be an absolute HTTP URL or root-relative path")
        origin = ""
    path = parts.path or "/"
    sanitized = f"{origin}{path}"
    if len(sanitized) > 2048:
        raise ValueError(f"{field} origin and path exceed 2048 characters")
    return sanitized


def _normalize_attribution(value: AttributionInput, property_slug: str) -> NormalizedAttribution:
    landing = value.landing_url or f"/properties/{property_slug}"
    return NormalizedAttribution(
        utm_source=_normalize_whitespace(value.utm_source),
        utm_medium=_normalize_whitespace(value.utm_medium),
        utm_campaign=_normalize_whitespace(value.utm_campaign),
        utm_content=_normalize_whitespace(value.utm_content),
        utm_term=_normalize_whitespace(value.utm_term),
        click_id_kind=value.click_id_kind,
        click_id_value=_normalize_whitespace(value.click_id_value),
        landing_path=sanitize_origin_path(landing, field="landingUrl"),
        referrer_origin_path=(
            sanitize_origin_path(value.referrer_url, field="referrerUrl") if value.referrer_url is not None else None
        ),
    )


def normalize_lead(value: LeadRequest) -> NormalizedLead:
    full_name = _normalize_whitespace(value.contact.full_name)
    message = _normalize_whitespace(value.inquiry.message)
    if full_name is None:
        raise AssertionError("validated full name cannot be None")
    return NormalizedLead(
        property_slug=value.property_slug,
        form_version=value.form_version,
        full_name=full_name,
        email=normalize_email(value.contact.email),
        phone=value.contact.phone,
        preferred_contact_method=value.contact.preferred_contact_method,
        intent=value.inquiry.intent,
        budget_band=value.inquiry.budget_band,
        timeframe=value.inquiry.timeframe,
        message=message,
        notice_version_assertion=value.consent.privacy_notice_version,
        requested_contact=value.consent.requested_contact,
        marketing_opt_in=value.consent.marketing,
        ad_measurement_opt_in=value.consent.ad_measurement,
        locale=value.consent.locale,
        attribution=_normalize_attribution(value.attribution, value.property_slug),
    )


def canonical_request_bytes(value: NormalizedLead) -> bytes:
    return json.dumps(
        value.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def request_sha256(value: NormalizedLead) -> bytes:
    return hashlib.sha256(canonical_request_bytes(value)).digest()
