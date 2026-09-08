from __future__ import annotations

import functools
import html
import smtplib
import socket
import ssl
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from enum import StrEnum

import sqlalchemy as sa
from email_validator import EmailNotValidError, validate_email
from sqlalchemy.orm import Session, sessionmaker

from real_estate_crm.config import Settings
from real_estate_crm.leads.models import Contact, Inquiry, Property

SMTP_TIMEOUT_SECONDS = 10


class DeliveryDisposition(StrEnum):
    SENT = "sent"
    TRANSIENT = "transient"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    disposition: DeliveryDisposition
    error_code: str | None = None
    message_id: str | None = None

    @classmethod
    def sent(cls, message_id: str) -> DeliveryResult:
        return cls(DeliveryDisposition.SENT, message_id=message_id)

    @classmethod
    def transient(cls, code: str) -> DeliveryResult:
        return cls(DeliveryDisposition.TRANSIENT, error_code=code)

    @classmethod
    def terminal(cls, code: str) -> DeliveryResult:
        return cls(DeliveryDisposition.TERMINAL, error_code=code)


def _default_smtp_factory(security: str) -> Callable[..., smtplib.SMTP]:
    """Select the transport for the configured security mode.

    `smtplib` defaults to an *unverified* SSL context when none is supplied, so
    both TLS paths pass an explicit verifying context instead.
    """
    if security == "tls":
        return functools.partial(smtplib.SMTP_SSL, context=ssl.create_default_context())
    return smtplib.SMTP


class EmailAdapter:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        *,
        smtp_factory: Callable[..., smtplib.SMTP] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._smtp_factory = smtp_factory or _default_smtp_factory(settings.smtp_security)

    def deliver(self, job_id: uuid.UUID, aggregate_id: uuid.UUID, payload: Mapping[str, object]) -> DeliveryResult:
        try:
            inquiry_id, property_id = self._parse_payload(payload)
            if inquiry_id != aggregate_id:
                return DeliveryResult.terminal("payload_aggregate_mismatch")
            message = self._build_message(job_id, inquiry_id, property_id)
        except (EmailNotValidError, ValueError):
            return DeliveryResult.terminal("invalid_email_configuration")
        except sa.exc.OperationalError:
            return DeliveryResult.transient("database_unavailable")

        try:
            with self._smtp_factory(
                self._settings.smtp_host,
                self._settings.smtp_port,
                timeout=SMTP_TIMEOUT_SECONDS,
            ) as client:
                if self._settings.smtp_security == "starttls":
                    client.starttls(context=ssl.create_default_context())
                if self._settings.smtp_username is not None:
                    password = self._settings.smtp_password
                    if password is None:
                        return DeliveryResult.terminal("smtp_auth_configuration")
                    client.login(self._settings.smtp_username, password.get_secret_value())
                client.send_message(message)
            return DeliveryResult.sent(str(message["Message-ID"]))
        except smtplib.SMTPAuthenticationError:
            return DeliveryResult.terminal("smtp_authentication")
        except smtplib.SMTPNotSupportedError:
            return DeliveryResult.terminal("smtp_tls_unsupported")
        except ssl.SSLCertVerificationError:
            return DeliveryResult.terminal("smtp_tls_certificate")
        except ssl.SSLError:
            return DeliveryResult.transient("smtp_tls_handshake")
        except smtplib.SMTPRecipientsRefused as exc:
            codes = [response[0] for response in exc.recipients.values()]
            return (
                DeliveryResult.transient("smtp_recipient_4xx")
                if codes and all(400 <= code < 500 for code in codes)
                else DeliveryResult.terminal("smtp_recipient_rejected")
            )
        except smtplib.SMTPResponseException as exc:
            return (
                DeliveryResult.transient("smtp_4xx")
                if 400 <= exc.smtp_code < 500
                else DeliveryResult.terminal("smtp_5xx")
            )
        except (TimeoutError, socket.timeout):
            return DeliveryResult.transient("smtp_timeout")
        except (ConnectionError, OSError, smtplib.SMTPException):
            return DeliveryResult.transient("smtp_connection")

    @staticmethod
    def _parse_payload(payload: Mapping[str, object]) -> tuple[uuid.UUID, uuid.UUID]:
        if set(payload) != {"inquiryId", "propertyId"}:
            raise ValueError("unexpected outbox payload")
        return uuid.UUID(str(payload["inquiryId"])), uuid.UUID(str(payload["propertyId"]))

    def _build_message(self, job_id: uuid.UUID, inquiry_id: uuid.UUID, property_id: uuid.UUID) -> EmailMessage:
        with self._session_factory() as session:
            row = session.execute(
                sa.select(Inquiry, Contact, Property)
                .join(Contact, Inquiry.contact_id == Contact.id)
                .join(Property, Inquiry.property_id == Property.id)
                .where(Inquiry.id == inquiry_id, Property.id == property_id)
            ).one_or_none()
        if row is None:
            raise ValueError("outbox entity not found")
        inquiry, contact, property_row = row
        sender = self._validated_address(self._settings.smtp_sender)
        recipients = tuple(self._validated_address(value) for value in self._settings.recipient_allow_list)
        if not recipients:
            raise ValueError("recipient allow-list is empty")
        domain = sender.rsplit("@", 1)[1]
        message_id = f"<{job_id}@{domain}>"
        values = {
            "reference": inquiry.public_reference,
            "property": property_row.title,
            "locality": property_row.locality,
            "name": contact.full_name,
            "email": contact.normalized_email or "Not supplied",
            "phone": contact.normalized_phone or "Not supplied",
            "intent": inquiry.intent or "Not supplied",
            "preferred": inquiry.preferred_contact_method or "Not supplied",
            "message": inquiry.message or "Not supplied",
        }
        plain = (
            "New property inquiry\n\n"
            f"Reference: {values['reference']}\nProperty: {values['property']}\nLocality: {values['locality']}\n"
            f"Name: {values['name']}\nEmail: {values['email']}\nPhone: {values['phone']}\n"
            f"Intent: {values['intent']}\nPreferred contact: {values['preferred']}\n\nMessage:\n{values['message']}\n"
        )
        escaped = {key: html.escape(str(value), quote=True) for key, value in values.items()}
        body = (
            "<h1>New property inquiry</h1>"
            f"<dl><dt>Reference</dt><dd>{escaped['reference']}</dd>"
            f"<dt>Property</dt><dd>{escaped['property']}</dd><dt>Locality</dt><dd>{escaped['locality']}</dd>"
            f"<dt>Name</dt><dd>{escaped['name']}</dd><dt>Email</dt><dd>{escaped['email']}</dd>"
            f"<dt>Phone</dt><dd>{escaped['phone']}</dd><dt>Intent</dt><dd>{escaped['intent']}</dd>"
            f"<dt>Preferred contact</dt><dd>{escaped['preferred']}</dd></dl>"
            f"<h2>Message</h2><p>{escaped['message'].replace(chr(10), '<br>')}</p>"
        )
        message = EmailMessage()
        message["Subject"] = f"New inquiry {inquiry.public_reference} — {property_row.title}"
        message["From"] = sender
        message["To"] = ", ".join(recipients)
        message["Message-ID"] = message_id
        message.set_content(plain)
        message.add_alternative(body, subtype="html")
        return message

    @staticmethod
    def _validated_address(value: str) -> str:
        if "\r" in value or "\n" in value:
            raise ValueError("email header injection")
        validated = validate_email(value, check_deliverability=False)
        if validated.normalized != value:
            raise ValueError("email address must already be normalized")
        return validated.normalized


__all__ = ["DeliveryDisposition", "DeliveryResult", "EmailAdapter", "SMTP_TIMEOUT_SECONDS"]
