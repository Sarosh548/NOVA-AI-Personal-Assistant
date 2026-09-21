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


class FakePreferences:
    def __init__(
        self,
        *,
        timezone="Asia/Karachi",
        enabled=True,
        delivery_hour=21,
        delivery_minute=0,
    ):
        self.timezone = timezone
        self.daily_activity_digest_enabled = (
            enabled
        )
        self.delivery_hour = delivery_hour
        self.delivery_minute = delivery_minute


class FakePreferencesService:
    def __init__(
        self,
        preferences_by_user,
    ):
        self.preferences_by_user = (
            preferences_by_user
        )
        self.calls = []

    def get_or_create(
        self,
        *,
        user_id,
    ):
        self.calls.append(
            user_id
        )

        return self.preferences_by_user.get(
            user_id,
            FakePreferences(),
        )


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


def build_scheduler(
    *,
    activity_event_service,
    notification_service,
    preferences_by_user,
):
    return ProactiveActivityScheduler(
        interval_seconds=5,
        activity_event_service=(
            activity_event_service
        ),
        notification_service=(
            notification_service
        ),
        preferences_service=(
            FakePreferencesService(
                preferences_by_user
            )
        ),
    )


def test_scheduler_is_due_for_user_local_time():
    preferences = FakePreferences(
        timezone="America/New_York",
        delivery_hour=11,
        delivery_minute=0,
    )

    before = datetime(
        2026,
        9,
        18,
        14,
        59,
        tzinfo=timezone.utc,
    )

    after = datetime(
        2026,
        9,
        18,
        15,
        0,
        tzinfo=timezone.utc,
    )

    assert (
        ProactiveActivityScheduler.is_due(
            preferences=preferences,
            now=before,
        )
        is False
    )

    assert (
        ProactiveActivityScheduler.is_due(
            preferences=preferences,
            now=after,
        )
        is True
    )


def test_scheduler_supports_different_global_users():
    ny_preferences = FakePreferences(
        timezone="America/New_York",
        delivery_hour=11,
        delivery_minute=0,
    )

    tokyo_preferences = FakePreferences(
        timezone="Asia/Tokyo",
        delivery_hour=2,
        delivery_minute=0,
    )

    now = datetime(
        2026,
        9,
        18,
        15,
        0,
        tzinfo=timezone.utc,
    )

    assert (
        ProactiveActivityScheduler.is_due(
            preferences=ny_preferences,
            now=now,
        )
        is True
    )

    assert (
        ProactiveActivityScheduler.is_due(
            preferences=tokyo_preferences,
            now=now,
        )
        is False
    )


def test_scheduler_rejects_invalid_interval():
    with pytest.raises(
        ValueError,
        match="interval_seconds must be at least 1",
    ):
        ProactiveActivityScheduler(
            interval_seconds=0,
            notification_service=(
                FakeProactiveNotificationService()
            ),
            preferences_service=(
                FakePreferencesService({})
            ),
        )


def test_scheduler_uses_current_local_day_for_each_user():
    (
        db_engine,
        activity_event_service,
    ) = build_runtime()

    try:
        create_event(
            activity_event_service,
            user_id="user-ny",
            created_at=datetime(
                2026,
                9,
                18,
                8,
                0,
            ),
        )

        notification_service = (
            FakeProactiveNotificationService()
        )

        scheduler = build_scheduler(
            activity_event_service=(
                activity_event_service
            ),
            notification_service=(
                notification_service
            ),
            preferences_by_user={
                "user-ny": FakePreferences(
                    timezone="America/New_York",
                    delivery_hour=11,
                    delivery_minute=0,
                ),
            },
        )

        results = asyncio.run(
            scheduler.process_daily_activity_digests(
                now=datetime(
                    2026,
                    9,
                    18,
                    15,
                    0,
                    tzinfo=timezone.utc,
                )
            )
        )

        assert [
            item["user_id"]
            for item in results
        ] == [
            "user-ny"
        ]

        assert [
            call["user_id"]
            for call in notification_service.calls
        ] == [
            "user-ny"
        ]

    finally:
        teardown_runtime(
            db_engine
        )


def test_scheduler_discovers_event_created_at_exact_now():
    (
        db_engine,
        activity_event_service,
    ) = build_runtime()

    try:
        now = datetime(
            2026,
            9,
            18,
            15,
            0,
            tzinfo=timezone.utc,
        )

        create_event(
            activity_event_service,
            user_id="user-tokyo",
            created_at=datetime(
                2026,
                9,
                18,
                15,
                0,
            ),
        )

        notification_service = (
            FakeProactiveNotificationService()
        )

        scheduler = build_scheduler(
            activity_event_service=(
                activity_event_service
            ),
            notification_service=(
                notification_service
            ),
            preferences_by_user={
                "user-tokyo": FakePreferences(
                    timezone="Asia/Tokyo",
                    delivery_hour=2,
                    delivery_minute=0,
                ),
            },
        )

        results = asyncio.run(
            scheduler.process_daily_activity_digests(
                now=now
            )
        )

        assert results[0]["user_id"] == (
            "user-tokyo"
        )

        assert (
            results[0]["result"]["reason"]
            == "not_due"
        )

        assert (
            notification_service.calls
            == []
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_scheduler_skips_disabled_user():
    (
        db_engine,
        activity_event_service,
    ) = build_runtime()

    try:
        create_event(
            activity_event_service,
            user_id="user-disabled",
            created_at=datetime(
                2026,
                9,
                18,
                15,
                0,
            ),
        )

        notification_service = (
            FakeProactiveNotificationService()
        )

        scheduler = build_scheduler(
            activity_event_service=(
                activity_event_service
            ),
            notification_service=(
                notification_service
            ),
            preferences_by_user={
                "user-disabled": FakePreferences(
                    enabled=False,
                    timezone="Asia/Karachi",
                    delivery_hour=1,
                    delivery_minute=0,
                ),
            },
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

        assert (
            results[0]["result"]["reason"]
            == "digest_disabled"
        )

        assert (
            notification_service.calls
            == []
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_scheduler_handles_multiple_users_independently():
    (
        db_engine,
        activity_event_service,
    ) = build_runtime()

    try:
        create_event(
            activity_event_service,
            user_id="user-ny",
            created_at=datetime(
                2026,
                9,
                18,
                10,
                0,
            ),
        )

        create_event(
            activity_event_service,
            user_id="user-karachi",
            created_at=datetime(
                2026,
                9,
                18,
                10,
                30,
            ),
        )

        notification_service = (
            FakeProactiveNotificationService()
        )

        scheduler = build_scheduler(
            activity_event_service=(
                activity_event_service
            ),
            notification_service=(
                notification_service
            ),
            preferences_by_user={
                "user-ny": FakePreferences(
                    timezone="America/New_York",
                    delivery_hour=11,
                    delivery_minute=0,
                ),
                "user-karachi": FakePreferences(
                    timezone="Asia/Karachi",
                    delivery_hour=22,
                    delivery_minute=0,
                ),
            },
        )

        results = asyncio.run(
            scheduler.process_daily_activity_digests(
                now=datetime(
                    2026,
                    9,
                    18,
                    16,
                    0,
                    tzinfo=timezone.utc,
                )
            )
        )

        delivered_users = [
            call["user_id"]
            for call in notification_service.calls
        ]

        assert delivered_users == [
            "user-ny"
        ]

        reasons = {
            item["user_id"]: item["result"]["reason"]
            for item in results
        }

        assert (
            reasons["user-ny"]
            == "delivered"
        )

        assert (
            reasons["user-karachi"]
            == "not_due"
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_scheduler_rejects_invalid_timezone_from_user_preferences():
    (
        db_engine,
        activity_event_service,
    ) = build_runtime()

    try:
        create_event(
            activity_event_service,
            user_id="user-invalid-timezone",
            created_at=datetime(
                2026,
                9,
                18,
                15,
                0,
            ),
        )

        notification_service = (
            FakeProactiveNotificationService()
        )

        scheduler = build_scheduler(
            activity_event_service=(
                activity_event_service
            ),
            notification_service=(
                notification_service
            ),
            preferences_by_user={
                "user-invalid-timezone": FakePreferences(
                    timezone="Invalid/Timezone",
                    delivery_hour=21,
                    delivery_minute=0,
                ),
            },
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

        assert (
            results[0]["result"]["reason"]
            == "scheduler_exception"
        )

        assert (
            notification_service.calls
            == []
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_scheduler_supports_dst_timezone():
    preferences = FakePreferences(
        timezone="America/New_York",
        delivery_hour=1,
        delivery_minute=30,
    )

    before_first_occurrence = datetime(
        2026,
        11,
        1,
        5,
        29,
        tzinfo=timezone.utc,
    )

    first_occurrence = datetime(
        2026,
        11,
        1,
        5,
        30,
        tzinfo=timezone.utc,
    )

    second_occurrence = datetime(
        2026,
        11,
        1,
        6,
        30,
        tzinfo=timezone.utc,
    )

    assert (
        ProactiveActivityScheduler.is_due(
            preferences=preferences,
            now=before_first_occurrence,
        )
        is False
    )

    assert (
        ProactiveActivityScheduler.is_due(
            preferences=preferences,
            now=first_occurrence,
        )
        is True
    )

    assert (
        ProactiveActivityScheduler.is_due(
            preferences=preferences,
            now=second_occurrence,
        )
        is True
    )


@pytest.mark.asyncio
async def test_scheduler_run_survives_cycle_failure(monkeypatch):
    scheduler = ProactiveActivityScheduler()
    calls = []
    sleeps = []

    async def flaky_cycle():
        calls.append("cycle")

        if len(calls) == 1:
            raise RuntimeError(
                "simulated cycle failure"
            )

        scheduler.stop()

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    scheduler.process_daily_activity_digests = flaky_cycle

    monkeypatch.setattr(
        "services.proactive_activity_scheduler.asyncio.sleep",
        fake_sleep,
    )

    await scheduler.run()

    assert calls == [
        "cycle",
        "cycle",
    ]
    assert sleeps == [
        scheduler.interval_seconds
    ]
    assert scheduler._running is False


@pytest.mark.asyncio
async def test_scheduler_cycle_backoff_caps_and_resets_after_success(monkeypatch):
    scheduler = ProactiveActivityScheduler()
    calls = []
    sleeps = []

    async def flaky_cycle():
        calls.append("cycle")

        if len(calls) <= 5:
            raise RuntimeError(
                "simulated cycle failure"
            )

        if len(calls) == 7:
            raise RuntimeError(
                "simulated post-recovery failure"
            )

        if len(calls) == 8:
            scheduler.stop()

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    scheduler.process_daily_activity_digests = flaky_cycle

    monkeypatch.setattr(
        "services.proactive_activity_scheduler.asyncio.sleep",
        fake_sleep,
    )

    await scheduler.run()

    assert calls == [
        "cycle",
        "cycle",
        "cycle",
        "cycle",
        "cycle",
        "cycle",
        "cycle",
        "cycle",
    ]
    assert sleeps == [
        scheduler.interval_seconds,
        scheduler.interval_seconds * 2,
        scheduler.interval_seconds * 4,
        scheduler.interval_seconds * 8,
        scheduler.MAX_CYCLE_BACKOFF_SECONDS,
        scheduler.interval_seconds,
        scheduler.interval_seconds,
    ]
    assert scheduler._running is False

