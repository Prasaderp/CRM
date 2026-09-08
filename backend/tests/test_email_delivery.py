from __future__ import annotations

import json
import smtplib
import ssl
import time
import uuid
from email.message import EmailMessage
from urllib.request import Request, urlopen
import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from factories import make_contact, make_inquiry, make_property
from real_estate_crm.config import Settings
from real_estate_crm.leads.models import Contact, Inquiry, Property
from real_estate_crm.notifications.email import (
    DeliveryDisposition,
    EmailAdapter,
    SMTP_TIMEOUT_SECONDS,
    _default_smtp_factory,
)


class CapturingSMTP:
    messages: list[EmailMessage] = []
    init_args: tuple[object, ...] = ()
    login_args: tuple[str, str] | None = None
    failure: BaseException | None = None
    calls: list[str] = []
    starttls_context: object = None
    starttls_failure: BaseException | None = None

    def __init__(self, *args: object, **kwargs: object) -> None:
        type(self).init_args = (*args, kwargs)

    def __enter__(self) -> CapturingSMTP:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def starttls(self, *, context: object = None) -> None:
        type(self).calls.append("starttls")
        type(self).starttls_context = context
        if self.starttls_failure:
            raise self.starttls_failure

    def login(self, username: str, password: str) -> None:
        type(self).calls.append("login")
        type(self).login_args = (username, password)

    def send_message(self, message: EmailMessage) -> None:
        type(self).calls.append("send_message")
        if self.failure:
            raise self.failure
        type(self).messages.append(message)


@pytest.fixture
def smtp() -> type[CapturingSMTP]:
    CapturingSMTP.messages, CapturingSMTP.login_args, CapturingSMTP.failure = [], None, None
    CapturingSMTP.calls, CapturingSMTP.starttls_context, CapturingSMTP.starttls_failure = [], None, None
    return CapturingSMTP


@pytest.fixture
def settings() -> Settings:
    return Settings.model_validate(
        {
            "environment": "local",
            "database_url": "postgresql://postgres:postgrespassword@127.0.0.1:5433/real_estate_crm_test",
            "public_origin": "http://localhost:5173",
            "canonical_notice_version": "test-v1",
            "canonical_notice_text": "Synthetic notice",
            "smtp_host": "127.0.0.1",
            "smtp_port": 1025,
            "smtp_security": "none",
            "smtp_sender": "leads@client.example",
            "recipient_allow_list": "agent@client.example",
            "secure_cookies": False,
        }
    )


@pytest.fixture
def email_entities(test_engine: sa.Engine):
    factory = sessionmaker(test_engine, expire_on_commit=False)
    property_id, contact_id, inquiry_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with factory.begin() as session:
        session.add(Property(**make_property(id=property_id, title="Unicode Ω Homes <script>")))
        session.add(Contact(**make_contact(id=contact_id, full_name="Test <Agent> Ω", email="person@example.com")))
        inquiry = make_inquiry(
            id=inquiry_id,
            contact_id=contact_id,
            property_id=property_id,
            public_reference="RE-ABC1234567",
        )
        session.add(Inquiry(**inquiry, message="Hello <img src=x onerror=alert(1)>\nSecond line"))
    yield factory, inquiry_id, property_id
    with factory.begin() as session:
        session.execute(sa.delete(Inquiry).where(Inquiry.id == inquiry_id))
        session.execute(sa.delete(Contact).where(Contact.id == contact_id))
        session.execute(sa.delete(Property).where(Property.id == property_id))


def _deliver(
    email_entities: tuple[sessionmaker[Session], uuid.UUID, uuid.UUID],
    settings: Settings,
    smtp: type[CapturingSMTP],
):
    factory, inquiry_id, property_id = email_entities
    job_id = uuid.uuid4()
    result = EmailAdapter(factory, settings, smtp_factory=smtp).deliver(
        job_id,
        inquiry_id,
        {"inquiryId": str(inquiry_id), "propertyId": str(property_id)},
    )
    return job_id, result


def test_unicode_multipart_html_escaping_allow_list_and_stable_message_id(
    email_entities: tuple[sessionmaker[Session], uuid.UUID, uuid.UUID],
    settings: Settings,
    smtp: type[CapturingSMTP],
) -> None:
    job_id, result = _deliver(email_entities, settings, smtp)
    assert result.disposition is DeliveryDisposition.SENT
    assert result.message_id == f"<{job_id}@client.example>"
    assert smtp.init_args == ("127.0.0.1", 1025, {"timeout": SMTP_TIMEOUT_SECONDS})
    message = smtp.messages[0]
    assert message["To"] == "agent@client.example"
    assert message["Message-ID"] == result.message_id
    plain = message.get_body(preferencelist=("plain",)).get_content()
    rendered_html = message.get_body(preferencelist=("html",)).get_content()
    assert "Test <Agent> Ω" in plain and "Unicode Ω Homes <script>" in plain
    assert "&lt;Agent&gt; Ω" in rendered_html and "&lt;script&gt;" in rendered_html
    assert "<img src=x" not in rendered_html and "&lt;img src=x onerror=alert(1)&gt;" in rendered_html
    assert "Budget: Not supplied" in plain and "Timeframe: Not supplied" in plain
    assert "View and manage this inquiry in CRM" in rendered_html
    assert f"/crm/inquiries/{email_entities[1]}" in rendered_html
    assert message["Reply-To"] == "person@example.com"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({}, "invalid_email_configuration"),
        (
            {"inquiryId": str(uuid.uuid4()), "propertyId": str(uuid.uuid4()), "pii": "forbidden"},
            "invalid_email_configuration",
        ),
    ],
)
def test_malformed_or_contract_breaching_payload_is_terminal(
    email_entities: tuple[sessionmaker[Session], uuid.UUID, uuid.UUID],
    settings: Settings,
    smtp: type[CapturingSMTP],
    payload: dict[str, object],
    expected: str,
) -> None:
    factory, inquiry_id, _ = email_entities
    result = EmailAdapter(factory, settings, smtp_factory=smtp).deliver(uuid.uuid4(), inquiry_id, payload)
    assert result.disposition is DeliveryDisposition.TERMINAL and result.error_code == expected
    assert smtp.messages == []


def test_payload_cannot_redirect_to_another_property(
    email_entities: tuple[sessionmaker[Session], uuid.UUID, uuid.UUID],
    settings: Settings,
    smtp: type[CapturingSMTP],
) -> None:
    factory, inquiry_id, _ = email_entities
    payload = {"inquiryId": str(inquiry_id), "propertyId": str(uuid.uuid4())}
    result = EmailAdapter(factory, settings, smtp_factory=smtp).deliver(uuid.uuid4(), inquiry_id, payload)
    assert result.disposition is DeliveryDisposition.TERMINAL
    assert smtp.messages == []


def test_header_injection_in_server_configuration_is_rejected(
    email_entities: tuple[sessionmaker[Session], uuid.UUID, uuid.UUID],
    settings: Settings,
    smtp: type[CapturingSMTP],
) -> None:
    poisoned = settings.model_copy(
        update={"recipient_allow_list_raw": "agent@client.example\r\nBcc: thief@example.com"}
    )
    _, result = _deliver(email_entities, poisoned, smtp)
    assert result.disposition is DeliveryDisposition.TERMINAL
    assert smtp.messages == []


@pytest.mark.parametrize(
    ("failure", "disposition", "code"),
    [
        (TimeoutError(), DeliveryDisposition.TRANSIENT, "smtp_timeout"),
        (ConnectionRefusedError(), DeliveryDisposition.TRANSIENT, "smtp_connection"),
        (smtplib.SMTPDataError(451, b"busy"), DeliveryDisposition.TRANSIENT, "smtp_4xx"),
        (smtplib.SMTPDataError(550, b"rejected"), DeliveryDisposition.TERMINAL, "smtp_5xx"),
        (smtplib.SMTPAuthenticationError(535, b"bad auth"), DeliveryDisposition.TERMINAL, "smtp_authentication"),
    ],
)
def test_smtp_failure_classification(
    email_entities: tuple[sessionmaker[Session], uuid.UUID, uuid.UUID],
    settings: Settings,
    smtp: type[CapturingSMTP],
    failure: BaseException,
    disposition: DeliveryDisposition,
    code: str,
) -> None:
    smtp.failure = failure
    _, result = _deliver(email_entities, settings, smtp)
    assert (result.disposition, result.error_code) == (disposition, code)


def test_authenticated_smtp_uses_secret_without_exposing_it(
    email_entities: tuple[sessionmaker[Session], uuid.UUID, uuid.UUID],
    settings: Settings,
    smtp: type[CapturingSMTP],
) -> None:
    authenticated = settings.model_copy(update={"smtp_username": "smtp-user", "smtp_password": SecretStr("secret")})
    _, result = _deliver(email_entities, authenticated, smtp)
    assert result.disposition is DeliveryDisposition.SENT
    assert smtp.login_args == ("smtp-user", "secret")


def test_mailpit_delivery_end_to_end(
    email_entities: tuple[sessionmaker[Session], uuid.UUID, uuid.UUID], settings: Settings
) -> None:
    factory, inquiry_id, property_id = email_entities
    job_id = uuid.uuid4()
    result = EmailAdapter(factory, settings).deliver(
        job_id,
        inquiry_id,
        {"inquiryId": str(inquiry_id), "propertyId": str(property_id)},
    )
    assert result.disposition is DeliveryDisposition.SENT
    found: dict[str, object] | None = None
    for _ in range(20):
        with urlopen("http://127.0.0.1:8025/api/v1/messages", timeout=2) as response:
            messages = json.load(response)["messages"]
        found = next(
            (message for message in messages if message.get("MessageID") == result.message_id.strip("<>")),
            None,
        )
        if found is not None:
            break
        time.sleep(0.05)
    assert found is not None and "RE-ABC1234567" in str(found["Subject"])
    delete_request = Request(
        "http://127.0.0.1:8025/api/v1/messages",
        data=json.dumps({"IDs": [str(found["ID"])]}).encode(),
        headers={"Content-Type": "application/json"},
        method="DELETE",
    )
    with urlopen(delete_request, timeout=2):
        pass


def _authenticated(settings: Settings, security: str) -> Settings:
    return settings.model_copy(
        update={
            "smtp_security": security,
            "smtp_username": "leads@client.example",
            "smtp_password": SecretStr("app-password"),
        }
    )


def test_starttls_is_negotiated_with_a_verifying_context_before_authenticating(
    email_entities: tuple[sessionmaker[Session], uuid.UUID, uuid.UUID],
    settings: Settings,
    smtp: type[CapturingSMTP],
) -> None:
    _, result = _deliver(email_entities, _authenticated(settings, "starttls"), smtp)
    assert result.disposition is DeliveryDisposition.SENT
    # Credentials must never cross an unencrypted connection.
    assert smtp.calls == ["starttls", "login", "send_message"]
    assert isinstance(smtp.starttls_context, ssl.SSLContext)
    assert smtp.starttls_context.verify_mode is ssl.CERT_REQUIRED
    assert smtp.starttls_context.check_hostname is True


def test_security_none_never_negotiates_tls(
    email_entities: tuple[sessionmaker[Session], uuid.UUID, uuid.UUID],
    settings: Settings,
    smtp: type[CapturingSMTP],
) -> None:
    _, result = _deliver(email_entities, settings, smtp)
    assert result.disposition is DeliveryDisposition.SENT
    assert smtp.calls == ["send_message"]


@pytest.mark.parametrize(
    ("security", "expected_class"),
    [("tls", smtplib.SMTP_SSL), ("starttls", smtplib.SMTP), ("none", smtplib.SMTP)],
)
def test_default_transport_matches_configured_security(
    settings: Settings, security: str, expected_class: type[smtplib.SMTP]
) -> None:
    factory = _default_smtp_factory(security)
    resolved = getattr(factory, "func", factory)
    assert resolved is expected_class
    if security == "tls":
        context = factory.keywords["context"]
        assert context.verify_mode is ssl.CERT_REQUIRED and context.check_hostname is True


@pytest.mark.parametrize(
    ("failure", "disposition", "code"),
    [
        (smtplib.SMTPNotSupportedError("no STARTTLS"), DeliveryDisposition.TERMINAL, "smtp_tls_unsupported"),
        (ssl.SSLCertVerificationError("bad certificate"), DeliveryDisposition.TERMINAL, "smtp_tls_certificate"),
        (ssl.SSLError("handshake interrupted"), DeliveryDisposition.TRANSIENT, "smtp_tls_handshake"),
    ],
)
def test_tls_failures_are_classified_and_never_fall_back_to_plaintext(
    email_entities: tuple[sessionmaker[Session], uuid.UUID, uuid.UUID],
    settings: Settings,
    smtp: type[CapturingSMTP],
    failure: BaseException,
    disposition: DeliveryDisposition,
    code: str,
) -> None:
    smtp.starttls_failure = failure
    _, result = _deliver(email_entities, _authenticated(settings, "starttls"), smtp)
    assert result.disposition is disposition and result.error_code == code
    assert smtp.messages == [] and smtp.login_args is None
