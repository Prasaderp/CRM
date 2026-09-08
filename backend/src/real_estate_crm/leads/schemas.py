from __future__ import annotations

import json
import unicodedata
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)

MAX_LEAD_BODY_BYTES = 16 * 1024


class LeadBodyTooLarge(ValueError):
    pass


class MalformedLeadBody(ValueError):
    pass


class InquiryIntent(StrEnum):
    BUY = "buy"
    RENT = "rent"
    SELL = "sell"
    INFORMATION = "information"


class PreferredContactMethod(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    WHATSAPP = "whatsapp"
    NO_PREFERENCE = "no_preference"


class BudgetBand(StrEnum):
    DOCUMENTED_MVP = "300000-400000"


class Timeframe(StrEnum):
    DOCUMENTED_MVP = "1-3-months"


class ClickIdKind(StrEnum):
    FACEBOOK = "fbclid"
    TIKTOK = "ttclid"
    X = "twclid"


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.title() for part in tail)


def _trim_safe_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    normalized = unicodedata.normalize("NFC", value.strip())
    if any(unicodedata.category(char) == "Cc" for char in normalized):
        raise ValueError("control characters are not allowed")
    return normalized


class PublicModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        extra="forbid",
        populate_by_name=False,
        str_strip_whitespace=False,
    )

    @field_validator("*", mode="before")
    @classmethod
    def reject_control_characters(cls, value: Any) -> Any:
        return _trim_safe_text(value)


class ContactInput(PublicModel):
    full_name: Annotated[StrictStr, Field(min_length=1, max_length=120)]
    email: Annotated[StrictStr, Field(min_length=3, max_length=254)] | None = None
    phone: Annotated[StrictStr, Field(pattern=r"^\+[1-9]\d{7,14}$")] | None = None
    preferred_contact_method: PreferredContactMethod | None = None

    @model_validator(mode="after")
    def validate_contact_methods(self) -> ContactInput:
        if self.email is None and self.phone is None:
            raise ValueError("at least one of email or phone is required")
        if self.preferred_contact_method == PreferredContactMethod.EMAIL and self.email is None:
            raise ValueError("preferred email contact requires an email")
        if (
            self.preferred_contact_method
            in {
                PreferredContactMethod.PHONE,
                PreferredContactMethod.WHATSAPP,
            }
            and self.phone is None
        ):
            raise ValueError("preferred phone or WhatsApp contact requires a phone")
        return self


class InquiryInput(PublicModel):
    intent: InquiryIntent | None = None
    budget_band: BudgetBand | None = None
    timeframe: Timeframe | None = None
    message: Annotated[StrictStr, Field(min_length=1, max_length=2000)] | None = None


class AttributionInput(PublicModel):
    utm_source: Annotated[StrictStr, Field(min_length=1, max_length=100)] | None = None
    utm_medium: Annotated[StrictStr, Field(min_length=1, max_length=100)] | None = None
    utm_campaign: Annotated[StrictStr, Field(min_length=1, max_length=200)] | None = None
    utm_content: Annotated[StrictStr, Field(min_length=1, max_length=200)] | None = None
    utm_term: Annotated[StrictStr, Field(min_length=1, max_length=200)] | None = None
    click_id_kind: ClickIdKind | None = None
    click_id_value: Annotated[StrictStr, Field(min_length=1, max_length=512)] | None = None
    landing_url: Annotated[StrictStr, Field(min_length=1)] | None = None
    referrer_url: Annotated[StrictStr, Field(min_length=1)] | None = None

    @model_validator(mode="after")
    def validate_click_id_pair(self) -> AttributionInput:
        if (self.click_id_kind is None) != (self.click_id_value is None):
            raise ValueError("clickIdKind and clickIdValue must be supplied together")
        return self


class ConsentInput(PublicModel):
    privacy_notice_version: Annotated[StrictStr, Field(min_length=1, max_length=40)]
    requested_contact: StrictBool
    marketing: StrictBool = False
    ad_measurement: StrictBool = False
    locale: Annotated[
        StrictStr,
        Field(min_length=2, max_length=20, pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$"),
    ] = "en-IN"

    @model_validator(mode="after")
    def require_contact_consent(self) -> ConsentInput:
        if not self.requested_contact:
            raise ValueError("requestedContact must be true")
        return self


class LeadRequest(PublicModel):
    property_slug: Annotated[
        StrictStr,
        Field(min_length=1, max_length=80, pattern=r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$"),
    ]
    form_version: Annotated[StrictStr, Field(min_length=1, max_length=40)]
    contact: ContactInput
    inquiry: InquiryInput = Field(default_factory=InquiryInput)
    attribution: AttributionInput = Field(default_factory=AttributionInput)
    consent: ConsentInput
    website: Annotated[StrictStr, Field(max_length=200)] = ""


class LeadAccepted(PublicModel):
    inquiry_id: uuid.UUID
    reference: Annotated[StrictStr, Field(pattern=r"^RE-[A-Z0-9]{10}$")]
    status: Literal["new"]
    submitted_at: datetime

    @field_validator("submitted_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("submittedAt must include a timezone")
        return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MalformedLeadBody(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite_number(value: str) -> None:
    raise MalformedLeadBody(f"non-finite JSON number is not allowed: {value}")


def parse_lead_request(body: bytes, *, max_bytes: int = MAX_LEAD_BODY_BYTES) -> LeadRequest:
    if len(body) > max_bytes:
        raise LeadBodyTooLarge(f"lead body exceeds {max_bytes} bytes")
    try:
        payload = json.loads(
            body,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise MalformedLeadBody("lead body must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise MalformedLeadBody("lead body must be a JSON object")
    return LeadRequest.model_validate(payload)
