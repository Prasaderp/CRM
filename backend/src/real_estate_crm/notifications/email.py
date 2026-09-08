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
from urllib.parse import quote

import sqlalchemy as sa
from email_validator import EmailNotValidError, validate_email
from sqlalchemy.orm import Session, sessionmaker

from real_estate_crm.config import Settings
from real_estate_crm.leads.models import Contact, Inquiry, Property

SMTP_TIMEOUT_SECONDS = 10


def _display_value(value: str | None) -> str:
    return value.strip() if value and value.strip() else "Not supplied"


def _title_case(value: str) -> str:
    return value.replace("_", " ").title() if value != "Not supplied" else value


def _render_plain(values: Mapping[str, str]) -> str:
    return (
        f"New {values['intent'].lower()} inquiry for {values['property']}\n"
        f"Reference: {values['reference']}\n\n"
        f"PROPERTY\n{values['property']}\n{values['locality']}\n\n"
        f"LEAD\n{values['name']}\nEmail: {values['email']}\nPhone: {values['phone']}\n\n"
        f"REQUIREMENTS\nIntent: {values['intent']}\nBudget: {values['budget']}\n"
        f"Timeframe: {values['timeframe']}\nPreferred contact: {values['preferred']}\n\n"
        f"MESSAGE\n{values['message']}\n\nOpen in CRM: {values['crm_url']}\nSubmitted: {values['submitted']}\n"
    )


def _render_html(values: Mapping[str, str]) -> str:
    escaped = {key: html.escape(value, quote=True) for key, value in values.items()}
    message_html = escaped["message"].replace("\n", "<br>")
    email_href = quote(values["email"], safe="@.+-")
    phone_href = quote(values["phone"], safe="+")
    email_action = (
        f'<a href="mailto:{email_href}" style="color:#ffffff;text-decoration:none;">Email lead</a>'
        if values["email"] != "Not supplied"
        else "Email not supplied"
    )
    phone_action = (
        f'<a href="tel:{phone_href}" style="color:#1f2937;text-decoration:none;">Call lead</a>'
        if values["phone"] != "Not supplied"
        else "Phone not supplied"
    )
    email_value = (
        f'<a href="mailto:{email_href}" style="color:#176b55;text-decoration:underline;">{escaped["email"]}</a>'
        if values["email"] != "Not supplied"
        else escaped["email"]
    )
    phone_value = (
        f'<a href="tel:{phone_href}" style="color:#176b55;text-decoration:underline;">{escaped["phone"]}</a>'
        if values["phone"] != "Not supplied"
        else escaped["phone"]
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#f3f4f6;color:#1f2937;font-family:Arial,Helvetica,sans-serif;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">New lead for {escaped["property"]} · {escaped["name"]}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;"><tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;">
<tr><td style="background:#173f35;padding:24px 32px;color:#ffffff;"><div style="font-size:12px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:#b9d4cb;">Real Estate CRM</div><h1 style="margin:8px 0 6px;font-size:26px;line-height:1.25;font-weight:700;">New property inquiry</h1><div style="font-size:14px;color:#dce9e5;">Reference {escaped["reference"]} · Submitted {escaped["submitted"]}</div></td></tr>
<tr><td style="padding:28px 32px 8px;"><div style="font-size:12px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:#6b7280;">Property</div><div style="margin-top:8px;font-size:21px;line-height:1.35;font-weight:700;color:#111827;">{escaped["property"]}</div><div style="margin-top:4px;font-size:15px;color:#4b5563;">{escaped["locality"]}</div></td></tr>
<tr><td style="padding:20px 32px 0;"><div style="border-top:1px solid #e5e7eb;"></div></td></tr>
<tr><td style="padding:24px 32px 8px;"><div style="font-size:12px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:#6b7280;">Lead details</div><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;font-size:15px;line-height:1.5;"><tr><td width="34%" style="padding:7px 12px 7px 0;color:#6b7280;">Name</td><td style="padding:7px 0;font-weight:700;color:#111827;">{escaped["name"]}</td></tr><tr><td style="padding:7px 12px 7px 0;color:#6b7280;">Email</td><td style="padding:7px 0;">{email_value}</td></tr><tr><td style="padding:7px 12px 7px 0;color:#6b7280;">Phone</td><td style="padding:7px 0;">{phone_value}</td></tr></table></td></tr>
<tr><td style="padding:18px 32px 8px;"><div style="font-size:12px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:#6b7280;">Requirements</div><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;font-size:15px;line-height:1.5;"><tr><td width="34%" style="padding:7px 12px 7px 0;color:#6b7280;">Intent</td><td style="padding:7px 0;color:#111827;">{escaped["intent"]}</td></tr><tr><td style="padding:7px 12px 7px 0;color:#6b7280;">Budget</td><td style="padding:7px 0;color:#111827;">{escaped["budget"]}</td></tr><tr><td style="padding:7px 12px 7px 0;color:#6b7280;">Timeframe</td><td style="padding:7px 0;color:#111827;">{escaped["timeframe"]}</td></tr><tr><td style="padding:7px 12px 7px 0;color:#6b7280;">Preferred contact</td><td style="padding:7px 0;color:#111827;">{escaped["preferred"]}</td></tr></table></td></tr>
<tr><td style="padding:20px 32px 8px;"><div style="font-size:12px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:#6b7280;">Message</div><div style="margin-top:10px;padding:16px;background:#f7f8f7;border-left:3px solid #b68a4a;border-radius:4px;font-size:15px;line-height:1.6;color:#374151;">{message_html}</div></td></tr>
<tr><td style="padding:24px 32px 32px;"><table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="background:#176b55;border-radius:6px;padding:12px 18px;font-size:14px;font-weight:700;">{email_action}</td><td width="10"></td><td style="border:1px solid #d1d5db;border-radius:6px;padding:11px 18px;font-size:14px;font-weight:700;">{phone_action}</td></tr></table><div style="margin-top:22px;font-size:13px;"><a href="{escaped["crm_url"]}" style="color:#176b55;text-decoration:underline;">View and manage this inquiry in CRM</a></div></td></tr>
</table><div style="max-width:640px;padding:16px 8px 0;font-size:12px;line-height:1.5;color:#6b7280;text-align:center;">This operational notification was sent to your configured lead recipients.</div>
</td></tr></table></body></html>"""


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
            "email": _display_value(contact.normalized_email),
            "phone": _display_value(contact.normalized_phone),
            "intent": _title_case(_display_value(inquiry.intent)),
            "budget": _display_value(inquiry.budget_band),
            "timeframe": _display_value(inquiry.timeframe),
            "preferred": _title_case(_display_value(inquiry.preferred_contact_method)),
            "message": _display_value(inquiry.message),
            "submitted": inquiry.submitted_at.strftime("%d %b %Y, %H:%M %Z").strip(),
            "crm_url": f"{str(self._settings.public_origin).rstrip('/')}/crm/inquiries/{inquiry.id}",
        }
        plain = _render_plain(values)
        body = _render_html(values)
        message = EmailMessage()
        message["Subject"] = f"New inquiry {inquiry.public_reference} — {property_row.title}"
        message["From"] = sender
        message["To"] = ", ".join(recipients)
        message["Message-ID"] = message_id
        if contact.normalized_email is not None:
            message["Reply-To"] = self._validated_address(contact.normalized_email)
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
