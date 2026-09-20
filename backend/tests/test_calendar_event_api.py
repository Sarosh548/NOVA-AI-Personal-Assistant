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
    get_google_calendar_service,
)


class FakeCalendarService:
    def __init__(self):
        self.calls = []
        self.list_result = {
            "events": [
                {
                    "id": "event-001",
                    "summary": "Planning",
                }
            ],
            "next_page_token": "page-2",
            "next_sync_token": "sync-1",
        }

    def list_events(self, **kwargs):
        self.calls.append(
            (
                "list",
                kwargs,
            )
        )
        return self.list_result

    def get_event(self, **kwargs):
        self.calls.append(
            (
                "get",
                kwargs,
            )
        )
        return {
            "id": kwargs["event_id"],
            "summary": "Planning",
        }

    def create_event(self, **kwargs):
        self.calls.append(
            (
                "create",
                kwargs,
            )
        )
        return {
            "id": "event-002",
            "summary": kwargs["event"]["summary"],
            "start": kwargs["event"]["start"],
            "end": kwargs["event"]["end"],
        }

    def update_event(self, **kwargs):
        self.calls.append(
            (
                "update",
                kwargs,
            )
        )
        return {
            "id": kwargs["event_id"],
            **kwargs["event"],
        }

    def delete_event(self, **kwargs):
        self.calls.append(
            (
                "delete",
                kwargs,
            )
        )
        return {
            "deleted": True,
            "event_id": kwargs["event_id"],
        }


def _authenticated_context(
    user_id="user-001",
):
    now = datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )

    return AuthenticatedContext(
        user=type(
            "UserStub",
            (),
            {
                "id": user_id,
                "is_active": True,
            },
        )(),
        session=type(
            "SessionStub",
            (),
            {
                "id": "calendar-event-api-session",
                "user_id": user_id,
            },
        )(),
    )


@pytest.fixture
def authenticated_client():
    service = FakeCalendarService()

    main.app.dependency_overrides[
        get_current_auth_context
    ] = lambda: _authenticated_context()

    main.app.dependency_overrides[
        get_google_calendar_service
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
            get_google_calendar_service,
            None,
        )


def test_calendar_events_require_authentication():
    client = TestClient(
        main.app
    )

    response = client.get(
        "/integrations/google/calendar/events"
    )

    assert response.status_code == 401


def test_list_calendar_events_uses_authenticated_user(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.get(
        "/integrations/google/calendar/events",
        params={
            "calendar_id": "primary",
            "time_min": "2026-09-21T00:00:00+05:00",
            "time_max": "2026-09-22T00:00:00+05:00",
            "query": "planning",
            "max_results": 20,
            "page_token": "page-1",
            "single_events": "true",
            "order_by": "startTime",
            "show_deleted": "false",
        },
    )

    assert response.status_code == 200
    assert response.json() == service.list_result

    assert service.calls[0] == (
        "list",
        {
            "user_id": "user-001",
            "calendar_id": "primary",
            "time_min": datetime(
                2026,
                9,
                21,
                0,
                0,
                tzinfo=timezone(
                    datetime.now(
                        timezone.utc
                    ).utcoffset()
                    or timezone.utc
                ),
            ),
            "time_max": datetime(
                2026,
                9,
                22,
                0,
                0,
                tzinfo=timezone(
                    datetime.now(
                        timezone.utc
                    ).utcoffset()
                    or timezone.utc
                ),
            ),
            "query": "planning",
            "max_results": 20,
            "page_token": "page-1",
            "single_events": True,
            "order_by": "startTime",
            "show_deleted": False,
        },
    )


def test_create_calendar_event_serializes_datetime_and_uses_auth_user(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.post(
        "/integrations/google/calendar/events",
        params={
            "calendar_id": "primary",
            "send_updates": "externalOnly",
        },
        json={
            "summary": "Team meeting",
            "start": {
                "dateTime": (
                    "2026-09-21T15:00:00+05:00"
                )
            },
            "end": {
                "dateTime": (
                    "2026-09-21T16:00:00+05:00"
                )
            },
            "attendees": [
                {
                    "email": "client@example.com",
                }
            ],
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == "event-002"

    action, payload = service.calls[0]

    assert action == "create"
    assert payload["user_id"] == "user-001"
    assert payload["calendar_id"] == "primary"
    assert payload["send_updates"] == "externalOnly"
    assert payload["event"] == {
        "summary": "Team meeting",
        "start": {
            "dateTime": (
                "2026-09-21T15:00:00+05:00"
            )
        },
        "end": {
            "dateTime": (
                "2026-09-21T16:00:00+05:00"
            )
        },
        "attendees": [
            {
                "email": "client@example.com",
            }
        ],
    }


def test_create_calendar_event_rejects_malformed_boundary(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.post(
        "/integrations/google/calendar/events",
        json={
            "summary": "Invalid",
            "start": {
                "dateTime": "2026-09-21T15:00:00"
            },
            "end": {
                "dateTime": (
                    "2026-09-21T16:00:00+05:00"
                )
            },
        },
    )

    assert response.status_code == 422
    assert service.calls == []


def test_update_calendar_event_requires_paired_time_fields(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.patch(
        "/integrations/google/calendar/events/event-001",
        json={
            "start": {
                "dateTime": (
                    "2026-09-21T15:00:00+05:00"
                )
            }
        },
    )

    assert response.status_code == 422
    assert service.calls == []


def test_get_calendar_event(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.get(
        "/integrations/google/calendar/events/event-001",
        params={
            "calendar_id": "primary",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": "event-001",
        "summary": "Planning",
    }

    assert service.calls[0] == (
        "get",
        {
            "user_id": "user-001",
            "event_id": "event-001",
            "calendar_id": "primary",
        },
    )


def test_update_calendar_event(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.patch(
        "/integrations/google/calendar/events/event-001",
        params={
            "calendar_id": "primary",
            "send_updates": "none",
        },
        json={
            "summary": "Renamed",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": "event-001",
        "summary": "Renamed",
    }

    assert service.calls[0] == (
        "update",
        {
            "user_id": "user-001",
            "event_id": "event-001",
            "calendar_id": "primary",
            "event": {
                "summary": "Renamed",
            },
            "send_updates": "none",
        },
    )


def test_delete_calendar_event(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.delete(
        "/integrations/google/calendar/events/event-001",
        params={
            "calendar_id": "primary",
            "send_updates": "all",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "deleted": True,
        "event_id": "event-001",
    }

    assert service.calls[0] == (
        "delete",
        {
            "user_id": "user-001",
            "event_id": "event-001",
            "calendar_id": "primary",
            "send_updates": "all",
        },
    )


def test_calendar_provider_404_is_preserved(
    authenticated_client,
):
    client, service = authenticated_client

    class MissingCalendarService(FakeCalendarService):
        def get_event(self, **_kwargs):
            from services.google_calendar_service import (
                GoogleCalendarAPIError,
            )

            raise GoogleCalendarAPIError(
                "Google Calendar resource was not found.",
                status_code=404,
            )

    replacement = MissingCalendarService()

    main.app.dependency_overrides[
        get_google_calendar_service
    ] = lambda: replacement

    response = client.get(
        "/integrations/google/calendar/events/event-missing"
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": (
            "Google Calendar resource was not found."
        )
    }


def test_calendar_api_does_not_accept_user_id_from_request(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.get(
        "/integrations/google/calendar/events",
        params={
            "user_id": "attacker-user",
        },
    )

    assert response.status_code == 200

    action, payload = service.calls[0]

    assert action == "list"
    assert payload["user_id"] == "user-001"
