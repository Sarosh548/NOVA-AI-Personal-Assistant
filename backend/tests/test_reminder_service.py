from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from database.base import Base
from models.reminder import Reminder
from services.reminder_service import ReminderService


@pytest.fixture
def reminder_service():
    engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    Base.metadata.create_all(
        engine,
        tables=[Reminder.__table__],
    )

    service = ReminderService(
        engine=engine
    )

    try:
        yield service
    finally:
        Base.metadata.drop_all(
            engine,
            tables=[Reminder.__table__],
        )
        engine.dispose()


def seed_reminder(
    service,
    *,
    status="pending",
    reminder_time=None,
    claim_token=None,
    lease_until=None,
):
    with Session(service.engine) as session:
        reminder = Reminder(
            user_id="user-001",
            title="Test reminder",
            reminder_time=(
                reminder_time
                or datetime(
                    2030,
                    1,
                    1,
                    10,
                    0,
                )
            ),
            status=status,
            claim_token=claim_token,
            lease_until=lease_until,
        )

        session.add(reminder)
        session.commit()
        session.refresh(reminder)

        return reminder.id


def get_reminder(
    service,
    reminder_id,
):
    with Session(service.engine) as session:
        return session.scalar(
            select(Reminder).where(
                Reminder.id == reminder_id
            )
        )


def test_claim_due_reminder_assigns_unique_lease(
    reminder_service,
):
    now = datetime(
        2030,
        1,
        1,
        12,
        0,
    )

    due_id = seed_reminder(
        reminder_service,
        reminder_time=(
            now - timedelta(minutes=1)
        ),
    )

    future_id = seed_reminder(
        reminder_service,
        reminder_time=(
            now + timedelta(minutes=1)
        ),
    )

    claimed = (
        reminder_service.claim_due_reminders(
            now=now
        )
    )

    assert [
        item["id"]
        for item in claimed
    ] == [due_id]

    item = claimed[0]

    assert item["status"] == "processing"
    assert item["claim_token"]
    assert item["lease_until"] == (
        now
        + timedelta(
            seconds=ReminderService.CLAIM_LEASE_SECONDS
        )
    )

    stored = get_reminder(
        reminder_service,
        due_id,
    )

    assert stored.status == "processing"
    assert stored.claim_token == item[
        "claim_token"
    ]
    assert stored.lease_until == item[
        "lease_until"
    ]

    future = get_reminder(
        reminder_service,
        future_id,
    )

    assert future.status == "pending"


def test_active_processing_lease_is_not_reclaimed(
    reminder_service,
):
    now = datetime(
        2030,
        1,
        1,
        12,
        0,
    )

    reminder_id = seed_reminder(
        reminder_service,
        status="processing",
        claim_token="active-token",
        lease_until=(
            now + timedelta(minutes=1)
        ),
    )

    claimed = (
        reminder_service.claim_due_reminders(
            now=now
        )
    )

    assert claimed == []

    stored = get_reminder(
        reminder_service,
        reminder_id,
    )

    assert stored.status == "processing"
    assert stored.claim_token == "active-token"


def test_claim_due_reminders_respects_batch_size(
    reminder_service,
):
    now = datetime(
        2030,
        1,
        1,
        12,
        0,
    )

    reminder_ids = [
        seed_reminder(
            reminder_service,
            reminder_time=(
                now - timedelta(minutes=3)
            ),
        ),
        seed_reminder(
            reminder_service,
            reminder_time=(
                now - timedelta(minutes=2)
            ),
        ),
        seed_reminder(
            reminder_service,
            reminder_time=(
                now - timedelta(minutes=1)
            ),
        ),
    ]

    claimed = reminder_service.claim_due_reminders(
        now=now,
        batch_size=2,
    )

    assert [item["id"] for item in claimed] == reminder_ids[:2]

    remaining = [
        get_reminder(
            reminder_service,
            reminder_id,
        )
        for reminder_id in reminder_ids
    ]

    assert [item.status for item in remaining] == [
        "processing",
        "processing",
        "pending",
    ]


@pytest.mark.parametrize(
    "batch_size",
    [0, 501],
)
def test_claim_due_reminders_rejects_invalid_batch_size(
    reminder_service,
    batch_size,
):
    with pytest.raises(
        ValueError,
        match="batch_size",
    ):
        reminder_service.claim_due_reminders(
            batch_size=batch_size,
        )


def test_expired_processing_lease_is_reclaimed_with_new_token(
    reminder_service,
):
    now = datetime(
        2030,
        1,
        1,
        12,
        0,
    )

    reminder_id = seed_reminder(
        reminder_service,
        status="processing",
        claim_token="old-token",
        lease_until=(
            now - timedelta(seconds=1)
        ),
    )

    claimed = (
        reminder_service.claim_due_reminders(
            now=now
        )
    )

    assert [
        item["id"]
        for item in claimed
    ] == [reminder_id]

    new_token = claimed[0][
        "claim_token"
    ]

    assert new_token != "old-token"

    assert (
        reminder_service.mark_reminder_completed(
            reminder_id,
            claim_token="old-token",
        )
        is False
    )

    assert (
        reminder_service.mark_reminder_completed(
            reminder_id,
            claim_token=new_token,
        )
        is True
    )

    stored = get_reminder(
        reminder_service,
        reminder_id,
    )

    assert stored.status == "completed"
    assert stored.claim_token is None
    assert stored.lease_until is None


def test_processing_without_lease_is_recoverable(
    reminder_service,
):
    now = datetime(
        2030,
        1,
        1,
        12,
        0,
    )

    reminder_id = seed_reminder(
        reminder_service,
        status="processing",
        claim_token=None,
        lease_until=None,
    )

    claimed = (
        reminder_service.claim_due_reminders(
            now=now
        )
    )

    assert [
        item["id"]
        for item in claimed
    ] == [reminder_id]

    assert claimed[0]["claim_token"]


def test_pending_transition_requires_current_claim(
    reminder_service,
):
    now = datetime(
        2030,
        1,
        1,
        12,
        0,
    )

    reminder_id = seed_reminder(
        reminder_service,
        status="processing",
        claim_token="current-token",
        lease_until=(
            now + timedelta(minutes=1)
        ),
    )

    assert (
        reminder_service.mark_reminder_pending(
            reminder_id,
            claim_token="wrong-token",
        )
        is False
    )

    assert (
        reminder_service.mark_reminder_pending(
            reminder_id,
            claim_token="current-token",
        )
        is True
    )

    stored = get_reminder(
        reminder_service,
        reminder_id,
    )

    assert stored.status == "pending"
    assert stored.claim_token is None
    assert stored.lease_until is None


def test_mark_completion_rejects_expired_current_lease(
    reminder_service,
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    reminder_id = seed_reminder(
        reminder_service,
        status="processing",
        claim_token="expired-token",
        lease_until=(
            now - timedelta(seconds=1)
        ),
    )

    assert (
        reminder_service.mark_reminder_completed(
            reminder_id,
            claim_token="expired-token",
        )
        is False
    )
