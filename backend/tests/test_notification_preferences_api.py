from datetime import datetime

from fastapi.testclient import TestClient

import main


class FakePreferences:
    def __init__(
        self,
        *,
        user_id="user-001",
        timezone="Asia/Karachi",
        enabled=True,
        delivery_hour=21,
        delivery_minute=0,
    ):
        self.id = 1
        self.user_id = user_id
        self.timezone = timezone
        self.daily_activity_digest_enabled = enabled
        self.delivery_hour = delivery_hour
        self.delivery_minute = delivery_minute
        self.created_at = datetime(
            2026,
            9,
            18,
            10,
            0,
        )
        self.updated_at = datetime(
            2026,
            9,
            18,
            10,
            0,
        )


class FakePreferencesService:
    def __init__(self):
        self.preferences = {}
        self.get_calls = []
        self.update_calls = []

    def get_or_create(
        self,
        *,
        user_id,
    ):
        self.get_calls.append(
            user_id
        )

        if user_id not in self.preferences:
            self.preferences[user_id] = (
                FakePreferences(
                    user_id=user_id
                )
            )

        return self.preferences[user_id]

    def update(
        self,
        *,
        user_id,
        timezone_name=None,
        daily_activity_digest_enabled=None,
        delivery_hour=None,
        delivery_minute=None,
    ):
        self.update_calls.append(
            {
                "user_id": user_id,
                "timezone_name": timezone_name,
                "daily_activity_digest_enabled": (
                    daily_activity_digest_enabled
                ),
                "delivery_hour": delivery_hour,
                "delivery_minute": delivery_minute,
            }
        )

        existing = self.preferences.get(
            user_id
        )

        if existing is None:
            existing = FakePreferences(
                user_id=user_id
            )
            self.preferences[user_id] = (
                existing
            )

        if timezone_name is not None:
            existing.timezone = timezone_name

        if (
            daily_activity_digest_enabled
            is not None
        ):
            existing.daily_activity_digest_enabled = (
                daily_activity_digest_enabled
            )

        if delivery_hour is not None:
            existing.delivery_hour = (
                delivery_hour
            )

        if delivery_minute is not None:
            existing.delivery_minute = (
                delivery_minute
            )

        existing.updated_at = datetime(
            2026,
            9,
            18,
            11,
            0,
        )

        return existing


def test_get_notification_preferences_returns_defaults(
    monkeypatch,
):
    service = FakePreferencesService()

    monkeypatch.setattr(
        main,
        "user_notification_preferences_service",
        service,
    )

    client = TestClient(
        main.app
    )

    response = client.get(
        "/users/user-001/notification-preferences"
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["id"] == 1
    assert payload["user_id"] == "user-001"
    assert payload["timezone"] == "Asia/Karachi"
    assert (
        payload["daily_activity_digest_enabled"]
        is True
    )
    assert payload["delivery_hour"] == 21
    assert payload["delivery_minute"] == 0

    assert service.get_calls == [
        "user-001"
    ]


def test_get_notification_preferences_is_user_scoped(
    monkeypatch,
):
    service = FakePreferencesService()

    monkeypatch.setattr(
        main,
        "user_notification_preferences_service",
        service,
    )

    client = TestClient(
        main.app
    )

    response = client.get(
        "/users/user-abc/notification-preferences"
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["user_id"] == "user-abc"


def test_put_notification_preferences_updates_all_fields(
    monkeypatch,
):
    service = FakePreferencesService()

    monkeypatch.setattr(
        main,
        "user_notification_preferences_service",
        service,
    )

    client = TestClient(
        main.app
    )

    response = client.put(
        "/users/user-001/notification-preferences",
        json={
            "timezone": "America/New_York",
            "daily_activity_digest_enabled": False,
            "delivery_hour": 8,
            "delivery_minute": 30,
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["timezone"] == (
        "America/New_York"
    )
    assert (
        payload["daily_activity_digest_enabled"]
        is False
    )
    assert payload["delivery_hour"] == 8
    assert payload["delivery_minute"] == 30

    assert service.update_calls == [
        {
            "user_id": "user-001",
            "timezone_name": (
                "America/New_York"
            ),
            "daily_activity_digest_enabled": False,
            "delivery_hour": 8,
            "delivery_minute": 30,
        }
    ]


def test_put_notification_preferences_supports_partial_updates(
    monkeypatch,
):
    service = FakePreferencesService()

    monkeypatch.setattr(
        main,
        "user_notification_preferences_service",
        service,
    )

    client = TestClient(
        main.app
    )

    first = client.put(
        "/users/user-001/notification-preferences",
        json={
            "timezone": "Europe/London",
            "delivery_hour": 7,
        },
    )

    assert first.status_code == 200

    payload = first.json()

    assert payload["timezone"] == (
        "Europe/London"
    )
    assert payload["delivery_hour"] == 7
    assert payload["delivery_minute"] == 0
    assert (
        payload["daily_activity_digest_enabled"]
        is True
    )


def test_put_notification_preferences_rejects_service_validation_error(
    monkeypatch,
):
    class RejectingPreferencesService(
        FakePreferencesService
    ):
        def update(
            self,
            *,
            user_id,
            timezone_name=None,
            daily_activity_digest_enabled=None,
            delivery_hour=None,
            delivery_minute=None,
        ):
            if timezone_name == "Invalid/Timezone":
                raise ValueError(
                    "Invalid timezone: Invalid/Timezone"
                )

            return super().update(
                user_id=user_id,
                timezone_name=timezone_name,
                daily_activity_digest_enabled=(
                    daily_activity_digest_enabled
                ),
                delivery_hour=delivery_hour,
                delivery_minute=delivery_minute,
            )

    service = RejectingPreferencesService()

    monkeypatch.setattr(
        main,
        "user_notification_preferences_service",
        service,
    )

    client = TestClient(
        main.app
    )

    response = client.put(
        "/users/user-001/notification-preferences",
        json={
            "timezone": "Invalid/Timezone",
        },
    )

    assert response.status_code == 400

    assert response.json() == {
        "detail": (
            "Invalid timezone: Invalid/Timezone"
        )
    }


def test_put_notification_preferences_rejects_invalid_hour_via_service(
    monkeypatch,
):
    class RejectingPreferencesService(
        FakePreferencesService
    ):
        def update(
            self,
            *,
            user_id,
            timezone_name=None,
            daily_activity_digest_enabled=None,
            delivery_hour=None,
            delivery_minute=None,
        ):
            if delivery_hour == 24:
                raise ValueError(
                    "delivery_hour must be between 0 and 23."
                )

            return super().update(
                user_id=user_id,
                timezone_name=timezone_name,
                daily_activity_digest_enabled=(
                    daily_activity_digest_enabled
                ),
                delivery_hour=delivery_hour,
                delivery_minute=delivery_minute,
            )

    service = RejectingPreferencesService()

    monkeypatch.setattr(
        main,
        "user_notification_preferences_service",
        service,
    )

    client = TestClient(
        main.app
    )

    response = client.put(
        "/users/user-001/notification-preferences",
        json={
            "delivery_hour": 24,
        },
    )

    assert response.status_code == 400

    assert response.json() == {
        "detail": (
            "delivery_hour must be between 0 and 23."
        )
    }