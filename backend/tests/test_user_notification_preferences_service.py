from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.user_notification_preferences import (
    UserNotificationPreferences,
)
from services.user_notification_preferences_service import (
    UserNotificationPreferencesService,
)


def _build_service():
    engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    UserNotificationPreferences.__table__.create(
        bind=engine
    )

    return (
        UserNotificationPreferencesService(
            engine=engine
        ),
        engine,
    )


def test_get_returns_none_for_unknown_user():
    service, engine = _build_service()

    try:
        assert (
            service.get(
                user_id="unknown-user"
            )
            is None
        )
    finally:
        engine.dispose()


def test_get_or_create_uses_global_safe_defaults():
    service, engine = _build_service()

    try:
        preferences = service.get_or_create(
            user_id="user-001"
        )

        assert preferences.user_id == "user-001"
        assert preferences.timezone == "Asia/Karachi"
        assert (
            preferences.daily_activity_digest_enabled
            is True
        )
        assert preferences.delivery_hour == 21
        assert preferences.delivery_minute == 0
    finally:
        engine.dispose()


def test_get_or_create_does_not_overwrite_existing_preferences():
    service, engine = _build_service()

    try:
        first = service.get_or_create(
            user_id="user-001",
            timezone_name="Europe/London",
            delivery_hour=19,
            delivery_minute=30,
        )

        second = service.get_or_create(
            user_id="user-001",
            timezone_name="Asia/Tokyo",
            delivery_hour=8,
            delivery_minute=15,
        )

        assert first.id == second.id
        assert second.timezone == "Europe/London"
        assert second.delivery_hour == 19
        assert second.delivery_minute == 30
    finally:
        engine.dispose()


def test_update_persists_global_user_preferences():
    service, engine = _build_service()

    try:
        updated = service.update(
            user_id="user-001",
            timezone_name="America/New_York",
            daily_activity_digest_enabled=False,
            delivery_hour=7,
            delivery_minute=45,
        )

        assert updated.timezone == "America/New_York"
        assert (
            updated.daily_activity_digest_enabled
            is False
        )
        assert updated.delivery_hour == 7
        assert updated.delivery_minute == 45

        loaded = service.get(
            user_id="user-001"
        )

        assert loaded is not None
        assert loaded.timezone == "America/New_York"
        assert (
            loaded.daily_activity_digest_enabled
            is False
        )
        assert loaded.delivery_hour == 7
        assert loaded.delivery_minute == 45
    finally:
        engine.dispose()


def test_update_can_create_missing_user_preferences():
    service, engine = _build_service()

    try:
        preferences = service.update(
            user_id="user-002",
            timezone_name="Asia/Tokyo",
            delivery_hour=8,
            delivery_minute=10,
        )

        assert preferences.user_id == "user-002"
        assert preferences.timezone == "Asia/Tokyo"
        assert preferences.delivery_hour == 8
        assert preferences.delivery_minute == 10
        assert (
            preferences.daily_activity_digest_enabled
            is True
        )
    finally:
        engine.dispose()


def test_invalid_timezone_is_rejected():
    service, engine = _build_service()

    try:
        try:
            service.get_or_create(
                user_id="user-001",
                timezone_name="Not/A/Timezone",
            )
        except ValueError as exc:
            assert str(exc) == (
                "Invalid timezone: Not/A/Timezone"
            )
        else:
            raise AssertionError(
                "Expected invalid timezone to raise ValueError."
            )
    finally:
        engine.dispose()


def test_invalid_delivery_hour_is_rejected():
    service, engine = _build_service()

    try:
        try:
            service.get_or_create(
                user_id="user-001",
                delivery_hour=24,
            )
        except ValueError as exc:
            assert str(exc) == (
                "delivery_hour must be between 0 and 23."
            )
        else:
            raise AssertionError(
                "Expected invalid hour to raise ValueError."
            )
    finally:
        engine.dispose()


def test_invalid_delivery_minute_is_rejected():
    service, engine = _build_service()

    try:
        try:
            service.get_or_create(
                user_id="user-001",
                delivery_minute=60,
            )
        except ValueError as exc:
            assert str(exc) == (
                "delivery_minute must be between 0 and 59."
            )
        else:
            raise AssertionError(
                "Expected invalid minute to raise ValueError."
            )
    finally:
        engine.dispose()


def test_invalid_enabled_value_is_rejected():
    service, engine = _build_service()

    try:
        try:
            service.get_or_create(
                user_id="user-001",
                daily_activity_digest_enabled=1,
            )
        except ValueError as exc:
            assert str(exc) == (
                "daily_activity_digest_enabled must be a boolean."
            )
        else:
            raise AssertionError(
                "Expected invalid enabled value to raise ValueError."
            )
    finally:
        engine.dispose()