from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from real_estate_crm.admin.service import (
    AdminService,
    InquiryFilters,
    InvalidCursor,
    InvalidInquiryMutation,
    StaleInquiryVersion,
)
from real_estate_crm.auth.models import AuditEvent, LeadStatusHistory, User
from real_estate_crm.leads.models import Contact, Inquiry, Property

NOW = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)


def _seed(session: Session, *, count: int = 3) -> tuple[User, Property, list[Inquiry]]:
    user = User(
        id=uuid.uuid4(),
        normalized_email=f"agent-{uuid.uuid4().hex}@example.com",
        display_name="Synthetic Agent",
        password_hash="$argon2id$synthetic",
        role="agent",
    )
    prop = Property(
        id=uuid.uuid4(),
        slug=f"crm-{uuid.uuid4().hex[:12]}",
        title="CRM Test Residence",
        summary="Synthetic",
        locality="Test City",
    )
    inquiries: list[Inquiry] = []
    for index in range(count):
        contact = Contact(
            id=uuid.uuid4(),
            full_name=f"Lead {index}",
            normalized_email=f"lead-{uuid.uuid4().hex}@example.com",
        )
        inquiry = Inquiry(
            id=uuid.uuid4(),
            public_reference=f"RE-{uuid.uuid4().hex[:10].upper()}",
            contact=contact,
            property=prop,
            source_platform="direct",
            form_version="property-inquiry-1.0",
            status="new",
            submitted_at=NOW - timedelta(minutes=index),
            assigned_user=user if index == 0 else None,
        )
        inquiries.append(inquiry)
    session.add_all([user, prop, *inquiries])
    session.flush()
    return user, prop, inquiries


def test_stable_cursor_filters_detail_and_active_assignee_projection(db_session: Session) -> None:
    user, prop, inquiries = _seed(db_session)
    service = AdminService(sessionmaker(bind=db_session.connection(), expire_on_commit=False))

    first = service.list_inquiries(page_size=2)
    second = service.list_inquiries(page_size=2, cursor=first.next_cursor)
    assert [item["id"] for item in first.items + second.items] == [str(item.id) for item in inquiries]
    assert len(set(item["id"] for item in first.items + second.items)) == 3
    assert second.next_cursor is None
    filtered = service.list_inquiries(filters=InquiryFilters(property_id=prop.id, assigned_user_id=user.id))
    assert [item["id"] for item in filtered.items] == [str(inquiries[0].id)]
    assert filtered.items[0]["contact"]["email"].startswith("lead-")
    assert service.list_active_users() == [{"id": str(user.id), "displayName": "Synthetic Agent", "role": "agent"}]
    detail = service.get_inquiry(inquiries[0].id)
    assert detail["property"]["id"] == str(prop.id) and detail["consent"] is None
    with pytest.raises(InvalidCursor):
        service.list_inquiries(cursor="not-valid-base64")


def test_status_and_assignment_are_atomic_versioned_and_audited(db_session: Session) -> None:
    actor, _, inquiries = _seed(db_session, count=1)
    assignee = User(
        id=uuid.uuid4(),
        normalized_email=f"assignee-{uuid.uuid4().hex}@example.com",
        display_name="Second Agent",
        password_hash="$argon2id$synthetic",
        role="agent",
    )
    db_session.add(assignee)
    db_session.flush()
    service = AdminService(sessionmaker(bind=db_session.connection(), expire_on_commit=False))
    request_id = uuid.uuid4()

    status = service.update_status(
        inquiries[0].id,
        status="contacted",
        expected_version=1,
        actor_user_id=actor.id,
        request_id=request_id,
    )
    assigned = service.update_assignment(
        inquiries[0].id,
        assigned_user_id=assignee.id,
        expected_version=2,
        actor_user_id=actor.id,
        request_id=request_id,
    )
    assert (status["status"], status["version"]) == ("contacted", 2)
    assert assigned["version"] == 3 and assigned["assignee"]["id"] == str(assignee.id)
    assert db_session.scalar(
        sa.select(sa.func.count()).select_from(LeadStatusHistory).where(LeadStatusHistory.inquiry_id == inquiries[0].id)
    ) == 1
    events = db_session.scalars(
        sa.select(AuditEvent).where(AuditEvent.entity_id == inquiries[0].id).order_by(AuditEvent.action)
    ).all()
    assert [event.action for event in events] == ["inquiry.assignment.changed", "inquiry.status.changed"]
    assert all(set(event.context) <= {"from_status", "to_status", "from_assignee_id", "to_assignee_id"} for event in events)
    with pytest.raises(StaleInquiryVersion):
        service.update_status(
            inquiries[0].id,
            status="qualified",
            expected_version=1,
            actor_user_id=actor.id,
            request_id=request_id,
        )
    with pytest.raises(InvalidInquiryMutation):
        service.update_assignment(
            inquiries[0].id,
            assigned_user_id=assignee.id,
            expected_version=3,
            actor_user_id=actor.id,
            request_id=request_id,
        )


def test_audit_failure_rolls_back_inquiry_and_history(db_session: Session) -> None:
    _, _, inquiries = _seed(db_session, count=1)
    service = AdminService(sessionmaker(bind=db_session.connection(), expire_on_commit=False))
    missing_actor = uuid.uuid4()
    with pytest.raises(sa.exc.IntegrityError):
        service.update_status(
            inquiries[0].id,
            status="qualified",
            expected_version=1,
            actor_user_id=missing_actor,
            request_id=uuid.uuid4(),
        )
    db_session.expire_all()
    persisted = db_session.get(Inquiry, inquiries[0].id)
    assert persisted and (persisted.status, persisted.version) == ("new", 1)
    assert db_session.scalar(
        sa.select(sa.func.count()).select_from(LeadStatusHistory).where(LeadStatusHistory.inquiry_id == inquiries[0].id)
    ) == 0


def test_simultaneous_mutations_commit_exactly_once(test_engine: sa.Engine) -> None:
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    with factory() as session, session.begin():
        actor, prop, inquiries = _seed(session, count=1)
        actor_id, property_id, inquiry_id, contact_id = (
            actor.id,
            prop.id,
            inquiries[0].id,
            inquiries[0].contact_id,
        )
    service, barrier = AdminService(factory), Barrier(2)

    def mutate(status: str) -> str:
        barrier.wait(timeout=5)
        try:
            service.update_status(
                inquiry_id,
                status=status,
                expected_version=1,
                actor_user_id=actor_id,
                request_id=uuid.uuid4(),
            )
            return "committed"
        except StaleInquiryVersion:
            return "stale"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = sorted(pool.map(mutate, ("contacted", "qualified")))
        assert outcomes == ["committed", "stale"]
        with factory() as session:
            row = session.get(Inquiry, inquiry_id)
            assert row and row.version == 2 and row.status in {"contacted", "qualified"}
            assert session.scalar(
                sa.select(sa.func.count()).select_from(LeadStatusHistory).where(
                    LeadStatusHistory.inquiry_id == inquiry_id
                )
            ) == 1
    finally:
        with test_engine.begin() as connection:
            connection.execute(sa.delete(AuditEvent).where(AuditEvent.entity_id == inquiry_id))
            connection.execute(sa.delete(Inquiry).where(Inquiry.id == inquiry_id))
            connection.execute(sa.delete(Contact).where(Contact.id == contact_id))
            connection.execute(sa.delete(Property).where(Property.id == property_id))
            connection.execute(sa.delete(User).where(User.id == actor_id))
