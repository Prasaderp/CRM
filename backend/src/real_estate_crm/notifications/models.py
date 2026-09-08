"""
Phase 4: Notifications domain ORM model — outbox_jobs queue row.

Design invariants (Architecture.md §4.3):
- payload contains only opaque entity IDs — no names, contact fields, SMTP credentials,
  or rendered email content.
- State / attempt / lock constraints are mirrored in both the ORM model and the migration;
  the migration is authoritative for the actual DDL.
- OutboxJob.aggregate_id references inquiries.id logically; the FK is expressed in the
  migration but NOT in this ORM model to avoid circular import issues at module load.
  The worker re-fetches the Inquiry after claiming the job, so this is safe.

Note: OutboxJob is defined in leads/models.py for the ORM (shared Base metadata).
This module re-exports it so notifications code can import from the canonical location.
It also ensures this file is importable by migrations/env.py for autogenerate coverage.
"""

from real_estate_crm.leads.models import OutboxJob  # noqa: F401

__all__ = ["OutboxJob"]
