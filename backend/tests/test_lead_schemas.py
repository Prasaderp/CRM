from __future__ import annotations

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from real_estate_crm.leads.normalization import (
    canonical_request_bytes,
    normalize_lead,
    request_sha256,
    sanitize_origin_path,
)
from real_estate_crm.leads.schemas import (
    MAX_LEAD_BODY_BYTES,
    LeadBodyTooLarge,
    LeadRequest,
    MalformedLeadBody,
    parse_lead_request,
)


@pytest.fixture
def valid_payload() -> dict[str, object]:
    return {
        "propertySlug": "test-property-alpha",
        "formVersion": "property-inquiry-1.0",
        "contact": {
            "fullName": "Example Person",
            "email": "Person@Example.COM",
            "phone": "+15551234567",
            "preferredContactMethod": "phone",
        },
        "inquiry": {
            "intent": "buy",
            "budgetBand": "300000-400000",
            "timeframe": "1-3-months",
            "message": "Please arrange a viewing.",
        },
        "attribution": {
            "utmSource": "instagram",
            "utmMedium": "paid_social",
            "utmCampaign": "summer-condos-2026",
            "clickIdKind": "fbclid",
            "clickIdValue": "opaque-click-id",
            "landingUrl": "https://Client.Example:443/properties/test-property-alpha?email=leak@example.com#form",
            "referrerUrl": "https://social.example/ad?token=secret",
        },
        "consent": {
            "privacyNoticeVersion": "client-assertion-only",
            "requestedContact": True,
            "marketing": False,
            "adMeasurement": False,
            "locale": "en-IN",
        },
    }


def _validate(payload: dict[str, object]) -> LeadRequest:
    return LeadRequest.model_validate(payload)


class TestStrictPublicContract:
    @pytest.mark.parametrize(
        ("path", "value"),
        [
            (("propertySlug",), "A" * 81),
            (("propertySlug",), "Uppercase-Slug"),
            (("formVersion",), "x" * 41),
            (("contact", "fullName"), "x" * 121),
            (("contact", "phone"), "15551234567"),
            (("contact", "phone"), "+0123456789"),
            (("contact", "phone"), "+1234567"),
            (("contact", "phone"), "+1234567890123456"),
            (("inquiry", "message"), "x" * 2001),
            (("attribution", "utmSource"), "x" * 101),
            (("attribution", "utmCampaign"), "x" * 201),
            (("attribution", "clickIdValue"), "x" * 513),
            (("consent", "locale"), "not a locale"),
        ],
    )
    def test_rejects_every_documented_boundary_breach(
        self,
        valid_payload: dict[str, object],
        path: tuple[str, ...],
        value: object,
    ) -> None:
        payload = deepcopy(valid_payload)
        target = payload
        for key in path[:-1]:
            target = target[key]  # type: ignore[assignment,index]
        target[path[-1]] = value  # type: ignore[index]
        with pytest.raises(ValidationError):
            _validate(payload)

    @pytest.mark.parametrize("contact", [{}, {"fullName": "Person"}])
    def test_requires_name_and_one_contact_method(
        self, valid_payload: dict[str, object], contact: dict[str, object]
    ) -> None:
        valid_payload["contact"] = contact
        with pytest.raises(ValidationError):
            _validate(valid_payload)

    @pytest.mark.parametrize(
        "contact",
        [
            {"fullName": "Person", "phone": "+15551234567", "preferredContactMethod": "email"},
            {"fullName": "Person", "email": "p@example.com", "preferredContactMethod": "phone"},
            {"fullName": "Person", "email": "p@example.com", "preferredContactMethod": "whatsapp"},
        ],
    )
    def test_preferred_method_must_be_usable(
        self, valid_payload: dict[str, object], contact: dict[str, object]
    ) -> None:
        valid_payload["contact"] = contact
        with pytest.raises(ValidationError):
            _validate(valid_payload)

    @pytest.mark.parametrize(
        ("container", "field", "value"),
        [
            (None, "unexpected", "value"),
            ("contact", "recipient", "attacker@example.com"),
            ("inquiry", "intent", "invest"),
            ("inquiry", "budgetBand", "unapproved-range"),
            ("inquiry", "timeframe", "eventually"),
            ("attribution", "clickIdKind", "gclid"),
            ("consent", "requestedContact", False),
            ("consent", "marketing", 1),
        ],
    )
    def test_rejects_unknown_fields_values_and_coercions(
        self,
        valid_payload: dict[str, object],
        container: str | None,
        field: str,
        value: object,
    ) -> None:
        target = valid_payload if container is None else valid_payload[container]
        target[field] = value  # type: ignore[index]
        with pytest.raises(ValidationError):
            _validate(valid_payload)

    @pytest.mark.parametrize("field", ["clickIdKind", "clickIdValue"])
    def test_click_identifier_is_an_atomic_pair(self, valid_payload: dict[str, object], field: str) -> None:
        del valid_payload["attribution"][field]  # type: ignore[index]
        with pytest.raises(ValidationError, match="supplied together"):
            _validate(valid_payload)

    @pytest.mark.parametrize("text", ["Bad\x00Name", "Line\nBreak", "Escape\x1bSequence"])
    def test_rejects_control_characters(self, valid_payload: dict[str, object], text: str) -> None:
        valid_payload["contact"]["fullName"] = text  # type: ignore[index]
        with pytest.raises(ValidationError, match="control characters"):
            _validate(valid_payload)


class TestNormalization:
    def test_normalizes_unicode_whitespace_and_email_without_dns(self, valid_payload: dict[str, object]) -> None:
        valid_payload["contact"] = {
            "fullName": "  Jose\u0301   Example  ",
            "email": "User@nonexistent-openai-example-987654321.com",
        }
        normalized = normalize_lead(_validate(valid_payload))
        assert normalized.full_name == "José Example"
        assert normalized.email == "User@nonexistent-openai-example-987654321.com"

    def test_strips_query_fragment_credentials_and_default_port(self, valid_payload: dict[str, object]) -> None:
        normalized = normalize_lead(_validate(valid_payload))
        assert normalized.attribution.landing_path == ("https://client.example/properties/test-property-alpha")
        assert normalized.attribution.referrer_origin_path == "https://social.example/ad"
        with pytest.raises(ValueError, match="credentials"):
            sanitize_origin_path("https://user:secret@example.com/path", field="landingUrl")

    @pytest.mark.parametrize(
        "url",
        ["javascript:alert(1)", "//evil.example/path", "relative/path", "https://example.com:bad/path"],
    )
    def test_rejects_unsafe_or_ambiguous_urls(self, url: str) -> None:
        with pytest.raises(ValueError):
            sanitize_origin_path(url, field="landingUrl")

    def test_click_metadata_cannot_override_trusted_fields(self, valid_payload: dict[str, object]) -> None:
        attribution = valid_payload["attribution"]
        attribution.update(  # type: ignore[union-attr]
            {
                "utmSource": "admin",
                "utmCampaign": "property=other-property&recipient=attacker@example.com",
                "clickIdValue": "source_platform=tiktok&authorized=true",
            }
        )
        normalized = normalize_lead(_validate(valid_payload))
        assert normalized.property_slug == "test-property-alpha"
        assert not hasattr(normalized, "recipient")
        assert not hasattr(normalized, "authorization")
        assert not hasattr(normalized, "source_platform")

    def test_canonical_bytes_are_stable_across_key_order_unicode_and_whitespace(
        self, valid_payload: dict[str, object]
    ) -> None:
        equivalent = json.loads(json.dumps(valid_payload, ensure_ascii=False))
        equivalent["contact"]["fullName"] = " José   Example "
        valid_payload["contact"]["fullName"] = "Jose\u0301 Example"
        equivalent = dict(reversed(list(equivalent.items())))
        first = normalize_lead(_validate(valid_payload))
        second = normalize_lead(_validate(equivalent))
        assert canonical_request_bytes(first) == canonical_request_bytes(second)
        assert request_sha256(first) == request_sha256(second)

    def test_meaningful_change_changes_hash(self, valid_payload: dict[str, object]) -> None:
        first = normalize_lead(_validate(valid_payload))
        valid_payload["inquiry"]["message"] = "A different request"  # type: ignore[index]
        second = normalize_lead(_validate(valid_payload))
        assert request_sha256(first) != request_sha256(second)


class TestBodyGate:
    def test_accepts_exactly_16_kib(self, valid_payload: dict[str, object]) -> None:
        encoded = json.dumps(valid_payload, separators=(",", ":")).encode()
        body = encoded + b" " * (MAX_LEAD_BODY_BYTES - len(encoded))
        assert len(body) == MAX_LEAD_BODY_BYTES
        assert parse_lead_request(body).property_slug == "test-property-alpha"

    def test_rejects_one_byte_over_before_parsing(self) -> None:
        with pytest.raises(LeadBodyTooLarge):
            parse_lead_request(b"{" + b" " * MAX_LEAD_BODY_BYTES)

    @pytest.mark.parametrize(
        "body",
        [
            b"[]",
            b"not-json",
            b'{"number":NaN}',
            b'{"propertySlug":"a","propertySlug":"b"}',
        ],
    )
    def test_rejects_non_object_malformed_and_duplicate_json(self, body: bytes) -> None:
        with pytest.raises(MalformedLeadBody):
            parse_lead_request(body)

    def test_deeply_nested_input_fails_without_escaping_the_validation_boundary(self) -> None:
        body = b'{"nested":' + b"[" * 1500 + b"]" * 1500 + b"}"
        with pytest.raises((MalformedLeadBody, ValidationError)):
            parse_lead_request(body)
