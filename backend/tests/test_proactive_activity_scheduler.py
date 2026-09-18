from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.activity_event import ActivityEvent
from services.activity_event_service import (
    ActivityEventService,
)
from services.proactive_activity_scheduler import (
    ProactiveActivityScheduler,
)


class FakeProactiveNotificationService:
    def __init__(self):
        self.calls = []

    def deliver_daily_activity_digest(
        self,
        *,
        user_id,
        now,
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "now": now,
            }
        )

        return {
            "delivered": True,
            "skipped": False,
            "reason": "delivered",
        }


def build_runtime():
    db_engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    ActivityEvent.__table__.create(
        bind=db_engine
    )

    activity_event_service = (
        ActivityEventService(
            db_engine=db_engine
        )
    )

    return (
        db_engine,
        activity_event_service,
    )


def teardown_runtime(
    db_engine,
):
    ActivityEvent.__table__.drop(
        bind=db_engine
    )

    db_engine.dispose()


def create_event(
    service,
    *,
    user_id,
    created_at,
):
    return service.record_event(
        user_id=user_id,
        event_type="task_created",
        source="tool_router",
        status="success",
        title="Task created",
        summary="Task created successfully.",
        created_at=created_at,
    )


def test_scheduler_is_due_after_configured_local_time():
    scheduler = ProactiveActivityScheduler(
        delivery_hour=21,
        delivery_minute=0,
        timezone_name="Asia/Karachi",
        notification_service=(
            FakeProactiveNotificationService()
        ),
    )

    before = datetime(
        2026,
        9,
        18,
        15,
        59,
        tzinfo=timezone.utc,
    )

    after = datetime(
        2026,
        9,
        18,
        16,
        0,
        tzinfo=timezone.utc,
    )

    assert scheduler.is_due(
        now=before
    ) is False

    assert scheduler.is_due(
        now=after
    ) is True


def test_scheduler_rejects_invalid_configuration():
    with pytest.raises(
        ValueError,
        match="interval_seconds must be at least 1",
    ):
        ProactiveActivityScheduler(
            interval_seconds=0,
            notification_service=(
                FakeProactiveNotificationService()
            ),
        )

    with pytest.raises(
        ValueError,
        match="delivery_hour",
    ):
        ProactiveActivityScheduler(
            delivery_hour=24,
            notification_service=(
                FakeProactiveNotificationService()
            ),
        )

    with pytest.raises(
        ValueError,
        match="delivery_minute",
    ):
        ProactiveActivityScheduler(
            delivery_minute=60,
            notification_service=(
                FakeProactiveNotificationService()
            ),
        )

    with pytest.raises(
        ValueError,
        match="Invalid scheduler timezone",
    ):
        ProactiveActivityScheduler(
            timezone_name="Invalid/Timezone",
            notification_service=(
                FakeProactiveNotificationService()
            ),
        )


def test_scheduler_discovers_only_current_local_day_users():
    db_engine, activity_event_service = (
        build_runtime()
    )

    try:
        create_event(
            activity_event_service,
            user_id="user-today",
            created_at=datetime(
                2026,
                9,
                18,
                17,
                0,
            ),
        )

        create_event(
            activity_event_service,
            user_id="user-yesterday",
            created_at=datetime(
                2026,
                9,
                17,
                17,
                0,
            ),
        )

        discovered = (
            activity_event_service
            .list_users_with_activity_since(
                since=datetime(
                    2026,
                    9,
                    18,
                    0,
                    0,
                ),
                until=datetime(
                    2026,
                    9,
                    19,
                    0,
                    0,
                ),
            )
        )

        assert discovered == [
            "user-today"
        ]

    finally:
        teardown_runtime(
            db_engine
        )


def test_scheduler_does_not_process_before_delivery_time():
    db_engine, activity_event_service = (
        build_runtime()
    )

    try:
        create_event(
            activity_event_service,
            user_id="user-001",
            created_at=datetime(
                2026,
                9,
                18,
                10,
                0,
            ),
        )

        notification_service = (
            FakeProactiveNotificationService()
        )

        scheduler = ProactiveActivityScheduler(
            activity_event_service=(
                activity_event_service
            ),
            notification_service=(
                notification_service
            ),
        )

        results = asyncio.run(
            scheduler.process_daily_activity_digests(
                now=datetime(
                    2026,
                    9,
                    18,
                    15,
                    59,
                    tzinfo=timezone.utc,
                )
            )
        )

        assert results == []

        assert (
            notification_service.calls
            == []
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_scheduler_processes_current_day_activity_users():
    db_engine, activity_event_service = (
        build_runtime()
    )

    try:
        create_event(
            activity_event_service,
            user_id="user-001",
            created_at=datetime(
                2026,
                9,
                18,
                17,
                0,
            ),
        )

        create_event(
            activity_event_service,
            user_id="user-001",
            created_at=datetime(
                2026,
                9,
                18,
                17,
                30,
            ),
        )

        create_event(
            activity_event_service,
            user_id="user-002",
            created_at=datetime(
                2026,
                9,
                18,
                16,
                0,
            ),
        )

        create_event(
            activity_event_service,
            user_id="user-old",
            created_at=datetime(
                2026,
                9,
                17,
                18,
                0,
            ),
        )

        notification_service = (
            FakeProactiveNotificationService()
        )

        scheduler = ProactiveActivityScheduler(
            activity_event_service=(
                activity_event_service
            ),
            notification_service=(
                notification_service
            ),
        )

        results = asyncio.run(
            scheduler.process_daily_activity_digests(
                now=datetime(
                    2026,
                    9,
                    18,
                    18,
                    0,
                    tzinfo=timezone.utc,
                )
            )
        )

        assert [
            item["user_id"]
            for item in results
        ] == [
            "user-001",
            "user-002",
        ]

        assert [
            call["user_id"]
            for call in notification_service.calls
        ] == [
            "user-001",
            "user-002",
        ]

        assert all(
            call["now"]
            == datetime(
                2026,
                9,
                18,
                18,
                0,
                tzinfo=timezone.utc,
            )
            for call in notification_service.calls
        )

    finally:
        teardown_runtime(
            db_engine
        )