from __future__ import annotations

import random
import string
import uuid


def make_property(
    *,
    id: uuid.UUID | None = None,
    slug: str = "test-property-alpha",
    title: str = "Test Property Alpha",
    locality: str = "Test City",
    is_active: bool = True,
) -> dict:
    """Return a dict of column values for a valid properties row."""
    return {
        "id": id or uuid.uuid4(),
        "slug": slug,
        "title": title,
        "summary": "A synthetic test property.",
        "locality": locality,
        "is_active": is_active,
    }


def make_contact(
    *,
    id: uuid.UUID | None = None,
    full_name: str = "Test Person",
    email: str | None = "testperson@example.com",
    phone: str | None = None,
) -> dict:
    """Return a dict of column values for a valid contacts row."""
    return {
        "id": id or uuid.uuid4(),
        "full_name": full_name,
        "normalized_email": email,
        "normalized_phone": phone,
    }


def make_inquiry(
    *,
    id: uuid.UUID | None = None,
    contact_id: uuid.UUID,
    property_id: uuid.UUID,
    public_reference: str | None = None,
    source_platform: str = "direct",
    form_version: str = "property-inquiry-1.0",
    status: str = "new",
) -> dict:
    """Return a dict of column values for a valid inquiries row.

    Generates a unique public_reference matching RE-[A-Z0-9]{10} each call.
    """
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
    ref = public_reference or f"RE-{suffix}"
    return {
        "id": id or uuid.uuid4(),
        "public_reference": ref,
        "contact_id": contact_id,
        "property_id": property_id,
        "source_platform": source_platform,
        "form_version": form_version,
        "status": status,
        "dedupe_state": "clear",
        "version": 1,
    }
