from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from real_estate_crm.config import Settings
from real_estate_crm.leads.normalization import NormalizedLead


@dataclass(frozen=True, slots=True)
class ConsentSnapshot:
    notice_version: str
    notice_text: str
    notice_sha256: bytes
    locale: str
    requested_contact: bool
    marketing_opt_in: bool
    ad_measurement_opt_in: bool
    capture_surface: str
    recorded_at: datetime


def build_consent_snapshot(lead: NormalizedLead, settings: Settings, *, recorded_at: datetime) -> ConsentSnapshot:
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    notice_text = settings.canonical_notice_text
    return ConsentSnapshot(
        notice_version=settings.canonical_notice_version,
        notice_text=notice_text,
        notice_sha256=hashlib.sha256(notice_text.encode("utf-8")).digest(),
        locale=lead.locale,
        requested_contact=True,
        marketing_opt_in=lead.marketing_opt_in,
        ad_measurement_opt_in=lead.ad_measurement_opt_in,
        capture_surface="website",
        recorded_at=recorded_at,
    )
