from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main

from api.auth import (
    AuthenticatedContext,
    get_current_auth_context,
)
from api.calendar import (
    get_google_calendar_oauth_service,
)
from models.user import User
from models.user_session import UserSession


class FakeGoogleCalendarOAuthService:
    def __init__(self):
        self.authorization_url = (
            "https://accounts.google.com/o/oauth2/v2/auth"
            "?client_id=test-client&state=test-state"
        )
        self.connect_calls = []
        self.complete_calls = []
        self.cancel_calls = []
        self.status_connection = None
        self.disconnect_result = True
        self.disconnect_calls = []

    def build_authorization_url(
        self,
        *,
        user_id,
    ):
        self.connect_calls.append(
            user_id
        )
        return self.authorization_url

    def cancel_authorization(
        self,
        *,
        state,
    ):
        self.cancel_calls.append(
            state
        )

    def complete_authorization(
        self,
        *,
        state,
        code,
    ):
        self.complete_calls.append(
            {
                "state": state,
                "code": code,
            }
        )
        return {
            "id": "calendar-connection-001",
            "user_id": "user-001",
            "provider": "google",
            "calendar_id": "primary",
            "scopes": (
                "https://www.googleapis.com/auth/calendar.events"
            ),
            "token_expires_at": datetime(
                2026,
                9,
                20,
                12,
                0,
            ),
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

    def get_connection(
        self,
        *,
        user_id,
    ):
        return self.status_connection

    def disconnect(
        self,
        *,
        user_id,
    ):
        self.disconnect_calls.append(
            user_id
        )
        return self.disconnect_result


def _authenticated_context(
    user_id="user-001",
):
    now = datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )

    user = User(
        id=user_id,
        display_name="Calendar API Test",
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    session = UserSession(
        id="calendar-api-test-session",
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
def authenticated_client():
    service = (
        FakeGoogleCalendarOAuthService()
    )

    main.app.dependency_overrides[
        get_current_auth_context
    ] = lambda: _authenticated_context()

    main.app.dependency_overrides[
        get_google_calendar_oauth_service
    ] = lambda: service

    client = TestClient(
        main.app
    )

    try:
        yield client, service

    finally:
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )
        main.app.dependency_overrides.pop(
            get_google_calendar_oauth_service,
            None,
        )


def test_connect_requires_authentication():
    client = TestClient(
        main.app
    )

    response = client.get(
        "/integrations/google/calendar/connect"
    )

    assert response.status_code == 401


def test_connect_returns_authorization_url(
    authenticated_client,
):
    client, service = (
        authenticated_client
    )

    response = client.get(
        "/integrations/google/calendar/connect"
    )

    assert response.status_code == 200
    assert response.json() == {
        "authorization_url": service.authorization_url
    }
    assert service.connect_calls == [
        "user-001"
    ]


def test_callback_completes_authorization(
    authenticated_client,
):
    client, service = (
        authenticated_client
    )

    response = client.get(
        "/integrations/google/calendar/callback",
        params={
            "state": "test-state",
            "code": "authorization-code",
        },
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "google"
    assert response.json()["calendar_id"] == "primary"
    assert service.complete_calls == [
        {
            "state": "test-state",
            "code": "authorization-code",
        }
    ]


def test_callback_google_denial_is_rejected(
    authenticated_client,
):
    client, service = (
        authenticated_client
    )

    response = client.get(
        "/integrations/google/calendar/callback",
        params={
            "state": "test-state",
            "error": "access_denied",
            "error_description": (
                "The user denied access."
            ),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Google Calendar authorization was "
        "not completed."
    )
    assert service.complete_calls == []
    assert service.cancel_calls == [
        "test-state"
    ]


def test_callback_without_code_is_rejected(
    authenticated_client,
):
    client, service = (
        authenticated_client
    )

    response = client.get(
        "/integrations/google/calendar/callback",
        params={
            "state": "test-state",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Google Calendar authorization code "
        "is required."
    )
    assert service.complete_calls == []


def test_status_returns_disconnected_state(
    authenticated_client,
):
    client, service = (
        authenticated_client
    )

    service.status_connection = None

    response = client.get(
        "/integrations/google/calendar/status"
    )

    assert response.status_code == 200
    assert response.json() == {
        "connected": False,
        "connection": None,
    }


def test_status_returns_connection(
    authenticated_client,
):
    client, service = (
        authenticated_client
    )

    service.status_connection = {
        "id": "calendar-connection-001",
        "user_id": "user-001",
        "provider": "google",
        "calendar_id": "primary",
        "scopes": (
            "https://www.googleapis.com/auth/calendar.events"
        ),
        "token_expires_at": datetime(
            2026,
            9,
            20,
            12,
            0,
        ),
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

    response = client.get(
        "/integrations/google/calendar/status"
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["connected"] is True
    assert payload["connection"]["id"] == (
        "calendar-connection-001"
    )
    assert payload["connection"]["user_id"] == (
        "user-001"
    )


def test_disconnect_removes_user_connection(
    authenticated_client,
):
    client, service = (
        authenticated_client
    )

    response = client.delete(
        "/integrations/google/calendar"
    )

    assert response.status_code == 204
    assert service.disconnect_calls == [
        "user-001"
    ]


def test_disconnect_without_connection_returns_404(
    authenticated_client,
):
    client, service = (
        authenticated_client
    )

    service.disconnect_result = False

    response = client.delete(
        "/integrations/google/calendar"
    )

    assert response.status_code == 404


def test_calendar_routes_derive_user_from_authentication(
    authenticated_client,
):
    client, service = (
        authenticated_client
    )

    response = client.get(
        "/integrations/google/calendar/connect"
    )

    assert response.status_code == 200
    assert service.connect_calls == [
        "user-001"
    ]
