from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import parse_qs, urlparse

import pytest

from services.google_calendar_service import (
    GoogleCalendarAPIError,
    GoogleCalendarService,
)


class FakeOAuthService:
    def __init__(
        self,
        *,
        connection=None,
    ):
        self.connection = connection or {
            "calendar_id": "primary",
        }
        self.access_token_calls = []
        self.connection_calls = []

    def get_connection(
        self,
        *,
        user_id,
    ):
        self.connection_calls.append(
            user_id
        )
        return self.connection

    def get_valid_access_token(
        self,
        *,
        user_id,
    ):
        self.access_token_calls.append(
            user_id
        )
        return "access-token-secret"


class FakeHTTPResponse:
    def __init__(
        self,
        body,
    ):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        return False

    def read(self):
        return self.body


def build_service(
    *,
    connection=None,
):
    oauth_service = FakeOAuthService(
        connection=connection
    )

    return (
        GoogleCalendarService(
            oauth_service=oauth_service
        ),
        oauth_service,
    )


def patch_response(
    monkeypatch,
    payload,
):
    captured = {}

    def fake_urlopen(
        request,
        timeout,
    ):
        captured["request"] = request
        captured["timeout"] = timeout

        if payload is None:
            return FakeHTTPResponse(
                b""
            )

        return FakeHTTPResponse(
            __import__(
                "json"
            ).dumps(
                payload
            ).encode(
                "utf-8"
            )
        )

    monkeypatch.setattr(
        "services.google_calendar_service.urlopen",
        fake_urlopen,
    )

    return captured


def test_list_events_uses_connection_calendar_and_paginates(
    monkeypatch,
):
    service, oauth = build_service()

    captured = patch_response(
        monkeypatch,
        {
            "items": [
                {
                    "id": "event-001",
                    "summary": "Planning",
                }
            ],
            "nextPageToken": "page-2",
            "nextSyncToken": "sync-1",
        },
    )

    result = service.list_events(
        user_id="user-001",
        time_min="2026-09-20T09:00:00+05:00",
        time_max="2026-09-20T18:00:00+05:00",
        query="planning meeting",
        max_results=20,
        page_token="page-1",
    )

    assert oauth.access_token_calls == [
        "user-001"
    ]

    assert result == {
        "events": [
            {
                "id": "event-001",
                "summary": "Planning",
            }
        ],
        "next_page_token": "page-2",
        "next_sync_token": "sync-1",
    }

    request = captured["request"]

    assert request.method == "GET"
    assert request.headers["Authorization"] == (
        "Bearer access-token-secret"
    )

    parsed = urlparse(
        request.full_url
    )
    assert parsed.path == (
        "/calendar/v3/calendars/primary/events"
    )

    query = parse_qs(
        parsed.query
    )

    assert query["timeMin"] == [
        "2026-09-20T09:00:00+05:00"
    ]
    assert query["timeMax"] == [
        "2026-09-20T18:00:00+05:00"
    ]
    assert query["q"] == [
        "planning meeting"
    ]
    assert query["maxResults"] == [
        "20"
    ]
    assert query["singleEvents"] == [
        "true"
    ]
    assert query["orderBy"] == [
        "startTime"
    ]
    assert query["pageToken"] == [
        "page-1"
    ]

    assert oauth.connection_calls == [
        "user-001"
    ]


def test_list_events_validates_query_shape():
    service, _oauth = build_service()

    with pytest.raises(
        ValueError,
        match="between 1 and 2500",
    ):
        service.list_events(
            user_id="user-001",
            max_results=0,
        )

    with pytest.raises(
        ValueError,
        match="order_by",
    ):
        service.list_events(
            user_id="user-001",
            order_by="summary",
        )


def test_get_event_uses_encoded_event_id(
    monkeypatch,
):
    service, _oauth = build_service()

    captured = patch_response(
        monkeypatch,
        {
            "id": "event/001",
            "summary": "One event",
        },
    )

    result = service.get_event(
        user_id="user-001",
        event_id="event/001",
    )

    assert result["id"] == "event/001"

    assert (
        urlparse(
            captured["request"].full_url
        ).path
        == (
            "/calendar/v3/calendars/"
            "primary/events/event%2F001"
        )
    )


def test_create_event_requires_start_and_end():
    service, _oauth = build_service()

    with pytest.raises(
        ValueError,
        match="start is required",
    ):
        service.create_event(
            user_id="user-001",
            event={
                "summary": "Missing start",
                "end": {
                    "dateTime": (
                        "2026-09-20T11:00:00+05:00"
                    )
                },
            },
        )

    with pytest.raises(
        ValueError,
        match="end is required",
    ):
        service.create_event(
            user_id="user-001",
            event={
                "summary": "Missing end",
                "start": {
                    "dateTime": (
                        "2026-09-20T10:00:00+05:00"
                    )
                },
            },
        )


def test_create_event_posts_event_and_send_updates(
    monkeypatch,
):
    service, _oauth = build_service()

    captured = patch_response(
        monkeypatch,
        {
            "id": "event-001",
            "summary": "Team meeting",
        },
    )

    result = service.create_event(
        user_id="user-001",
        event={
            "summary": "Team meeting",
            "start": {
                "dateTime": (
                    "2026-09-20T10:00:00+05:00"
                )
            },
            "end": {
                "dateTime": (
                    "2026-09-20T11:00:00+05:00"
                )
            },
        },
    )

    assert result["id"] == "event-001"

    request = captured["request"]

    assert request.method == "POST"

    query = parse_qs(
        urlparse(
            request.full_url
        ).query
    )

    assert query["sendUpdates"] == [
        "all"
    ]

    assert request.headers[
        "Content-Type"
    ] == "application/json"

    import json

    assert json.loads(
        request.data.decode(
            "utf-8"
        )
    ) == {
        "summary": "Team meeting",
        "start": {
            "dateTime": (
                "2026-09-20T10:00:00+05:00"
            )
        },
        "end": {
            "dateTime": (
                "2026-09-20T11:00:00+05:00"
            )
        },
    }


def test_update_event_uses_patch_and_requires_paired_times(
    monkeypatch,
):
    service, _oauth = build_service()

    with pytest.raises(
        ValueError,
        match="both start and end",
    ):
        service.update_event(
            user_id="user-001",
            event_id="event-001",
            event={
                "start": {
                    "dateTime": (
                        "2026-09-20T10:00:00+05:00"
                    )
                }
            },
        )

    captured = patch_response(
        monkeypatch,
        {
            "id": "event-001",
            "summary": "Renamed",
        },
    )

    result = service.update_event(
        user_id="user-001",
        event_id="event-001",
        event={
            "summary": "Renamed",
        },
        send_updates="externalOnly",
    )

    assert result["summary"] == "Renamed"
    assert captured["request"].method == "PATCH"

    query = parse_qs(
        urlparse(
            captured["request"].full_url
        ).query
    )

    assert query["sendUpdates"] == [
        "externalOnly"
    ]


def test_update_event_rejects_empty_payload():
    service, _oauth = build_service()

    with pytest.raises(
        ValueError,
        match="cannot be empty",
    ):
        service.update_event(
            user_id="user-001",
            event_id="event-001",
            event={},
        )


def test_delete_event_handles_empty_google_response(
    monkeypatch,
):
    service, _oauth = build_service()

    captured = patch_response(
        monkeypatch,
        None,
    )

    result = service.delete_event(
        user_id="user-001",
        event_id="event-001",
    )

    assert result == {
        "deleted": True,
        "event_id": "event-001",
    }

    assert captured["request"].method == "DELETE"

    query = parse_qs(
        urlparse(
            captured["request"].full_url
        ).query
    )

    assert query["sendUpdates"] == [
        "all"
    ]


def test_invalid_send_updates_is_rejected():
    service, _oauth = build_service()

    with pytest.raises(
        ValueError,
        match="send_updates",
    ):
        service.create_event(
            user_id="user-001",
            send_updates="sometimes",
            event={
                "summary": "Invalid",
                "start": {
                    "dateTime": (
                        "2026-09-20T10:00:00+05:00"
                    )
                },
                "end": {
                    "dateTime": (
                        "2026-09-20T11:00:00+05:00"
                    )
                },
            },
        )


def test_datetime_list_filters_require_timezone_aware_datetime():
    service, _oauth = build_service()

    naive_datetime = datetime(
        2026,
        9,
        20,
        10,
        0,
    )

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        service.list_events(
            user_id="user-001",
            time_min=naive_datetime,
        )


def test_http_errors_are_sanitized(
    monkeypatch,
):
    service, _oauth = build_service()

    def fake_urlopen(
        request,
        timeout,
    ):
        raise __import__(
            "urllib.error"
        ).error.HTTPError(
            request.full_url,
            403,
            "forbidden",
            {},
            BytesIO(
                b'{"error":{"message":"PRIVATE EVENT DETAILS"}}'
            ),
        )

    monkeypatch.setattr(
        "services.google_calendar_service.urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        GoogleCalendarAPIError,
        match="access was denied",
    ) as exc_info:
        service.get_event(
            user_id="user-001",
            event_id="event-001",
        )

    assert (
        "PRIVATE EVENT DETAILS"
        not in str(
            exc_info.value
        )
    )


def test_missing_calendar_connection_fails_before_provider_call():
    service, oauth = build_service(
        connection=None
    )

    oauth.connection = None

    with pytest.raises(
        ValueError,
        match="not connected",
    ):
        service.list_events(
            user_id="user-001"
        )

    assert oauth.access_token_calls == []
