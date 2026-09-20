from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main

from api.auth import (
    AuthenticatedContext,
    get_current_auth_context,
)
from api.notification_destinations import (
    get_notification_destination_service,
)
from models.user import User
from models.user_session import UserSession


class FakeDestinationService:
    def __init__(self):
        self.destinations = [
            {
                "id": 1,
                "user_id": "user-001",
                "channel": "email",
                "destination": "sarosh@example.com",
                "label": "Primary",
                "is_enabled": True,
                "is_default": True,
                "created_at": datetime(
                    2026,
                    9,
                    20,
                    10,
                    0,
                ),
                "updated_at": datetime(
                    2026,
                    9,
                    20,
                    10,
                    0,
                ),
            }
        ]

        self.create_calls = []
        self.default_calls = []
        self.delete_calls = []

    def list_destinations(
        self,
        *,
        user_id,
        channel=None,
        include_disabled=True,
    ):
        return [
            item
            for item in self.destinations
            if item["user_id"] == user_id
            and (
                channel is None
                or item["channel"] == channel
            )
        ]

    def create_destination(
        self,
        *,
        user_id,
        channel,
        destination,
        label=None,
        is_default=False,
    ):
        self.create_calls.append(
            {
                "user_id": user_id,
                "channel": channel,
                "destination": destination,
                "label": label,
                "is_default": is_default,
            }
        )

        result = {
            "id": 2,
            "user_id": user_id,
            "channel": channel,
            "destination": destination,
            "label": label,
            "is_enabled": True,
            "is_default": is_default,
            "created_at": datetime(
                2026,
                9,
                20,
                11,
                0,
            ),
            "updated_at": datetime(
                2026,
                9,
                20,
                11,
                0,
            ),
        }

        self.destinations.append(
            result
        )

        return result

    def set_default_destination(
        self,
        *,
        user_id,
        destination_id,
    ):
        self.default_calls.append(
            {
                "user_id": user_id,
                "destination_id": destination_id,
            }
        )

        for item in self.destinations:
            if item["user_id"] == user_id:
                item["is_default"] = (
                    item["id"] == destination_id
                )

        return next(
            (
                item
                for item in self.destinations
                if item["id"] == destination_id
                and item["user_id"] == user_id
            ),
            None,
        )

    def delete_destination(
        self,
        *,
        user_id,
        destination_id,
    ):
        self.delete_calls.append(
            {
                "user_id": user_id,
                "destination_id": destination_id,
            }
        )

        before = len(
            self.destinations
        )

        self.destinations = [
            item
            for item in self.destinations
            if not (
                item["id"] == destination_id
                and item["user_id"] == user_id
            )
        ]

        return len(
            self.destinations
        ) < before


def _authenticated_context(
    user_id: str,
):
    now = datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )

    user = User(
        id=user_id,
        display_name="Notification Destination Test",
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    session = UserSession(
        id="notification-destination-test-session",
        user_id=user_id,
        refresh_token_hash="c" * 64,
        expires_at=now.replace(
            year=now.year + 1
        ),
        last_used_at=now,
        revoked_at=None,
        created_at=now,
        updated_at=now,
    )

    return AuthenticatedContext(
        user=user,
        session=session,
    )


@pytest.fixture
def authenticated_client(monkeypatch):
    service = FakeDestinationService()

    main.app.dependency_overrides[
        get_current_auth_context
    ] = lambda: _authenticated_context(
        "user-001"
    )

    main.app.dependency_overrides[
        get_notification_destination_service
    ] = lambda: service

    client = TestClient(
        main.app
    )

    try:
        yield (
            client,
            service,
        )
    finally:
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )

        main.app.dependency_overrides.pop(
            get_notification_destination_service,
            None,
        )


def test_list_notification_destinations(
    authenticated_client,
):
    client, _service = (
        authenticated_client
    )

    response = client.get(
        "/notification-destinations"
    )

    assert response.status_code == 200

    payload = response.json()

    assert len(payload) == 1
    assert payload[0]["channel"] == "email"
    assert (
        payload[0]["destination"]
        == "sarosh@example.com"
    )
    assert payload[0]["is_default"] is True


def test_create_notification_destination(
    authenticated_client,
):
    client, service = (
        authenticated_client
    )

    response = client.post(
        "/notification-destinations",
        json={
            "channel": "email",
            "destination": "new@example.com",
            "label": "Secondary",
            "is_default": True,
        },
    )

    assert response.status_code == 201

    payload = response.json()

    assert payload["destination"] == (
        "new@example.com"
    )

    assert service.create_calls == [
        {
            "user_id": "user-001",
            "channel": "email",
            "destination": "new@example.com",
            "label": "Secondary",
            "is_default": True,
        }
    ]


def test_set_default_notification_destination(
    authenticated_client,
):
    client, service = (
        authenticated_client
    )

    response = client.post(
        "/notification-destinations/1/default"
    )

    assert response.status_code == 200

    assert service.default_calls == [
        {
            "user_id": "user-001",
            "destination_id": 1,
        }
    ]

    assert response.json()["is_default"] is True


def test_delete_notification_destination(
    authenticated_client,
):
    client, service = (
        authenticated_client
    )

    response = client.delete(
        "/notification-destinations/1"
    )

    assert response.status_code == 204

    assert service.delete_calls == [
        {
            "user_id": "user-001",
            "destination_id": 1,
        }
    ]


def test_notification_destinations_require_authentication():
    main.app.dependency_overrides.pop(
        get_current_auth_context,
        None,
    )

    client = TestClient(
        main.app
    )

    response = client.get(
        "/notification-destinations"
    )

    assert response.status_code == 401


def test_notification_destinations_do_not_allow_other_user():
    main.app.dependency_overrides[
        get_current_auth_context
    ] = lambda: _authenticated_context(
        "user-001"
    )

    service = FakeDestinationService()

    main.app.dependency_overrides[
        get_notification_destination_service
    ] = lambda: service

    client = TestClient(
        main.app
    )

    try:
        # Destination routes derive identity from the authenticated
        # user rather than accepting a user_id path parameter.
        response = client.post(
            "/notification-destinations",
            json={
                "channel": "email",
                "destination": "other@example.com",
            },
        )

        assert response.status_code == 201

        assert service.create_calls[0][
            "user_id"
        ] == "user-001"

    finally:
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )

        main.app.dependency_overrides.pop(
            get_notification_destination_service,
            None,
        )