from __future__ import annotations

from datetime import datetime

import pytest

from agent import graph
from services.google_calendar_service import (
    GoogleCalendarService,
)
from services.google_calendar_tool_service import (
    GoogleCalendarToolService,
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

    def get_connection(
        self,
        *,
        user_id,
    ):
        return self.connection

    def get_valid_access_token(
        self,
        *,
        user_id,
    ):
        self.access_token_calls.append(
            user_id
        )
        return "access-token"


def build_service():
    oauth_service = FakeOAuthService()

    return (
        GoogleCalendarService(
            oauth_service=oauth_service
        ),
        oauth_service,
    )


def timed_event(
    *,
    start="2026-09-21T15:00:00+05:00",
    end="2026-09-21T16:00:00+05:00",
):
    return {
        "summary": "Team meeting",
        "start": {
            "dateTime": start,
        },
        "end": {
            "dateTime": end,
        },
    }


def all_day_event():
    return {
        "summary": "Holiday",
        "start": {
            "date": "2026-09-21",
        },
        "end": {
            "date": "2026-09-22",
        },
    }


@pytest.mark.parametrize(
    "event,match",
    [
        (
            {
                **timed_event(),
                "unexpected": "provider-field",
            },
            "unsupported fields",
        ),
        (
            {
                "summary": "Bad start",
                "start": {
                    "dateTime": (
                        "2026-09-21T15:00:00+05:00"
                    ),
                    "date": "2026-09-21",
                },
                "end": {
                    "dateTime": (
                        "2026-09-21T16:00:00+05:00"
                    )
                },
            },
            "exactly one",
        ),
        (
            {
                "summary": "Bad end",
                "start": {
                    "dateTime": (
                        "2026-09-21T15:00:00+05:00"
                    )
                },
                "end": {
                    "dateTime": (
                        "2026-09-21T16:00:00"
                    )
                },
            },
            "timezone offset",
        ),
        (
            {
                "summary": "Bad date",
                "start": {
                    "date": "21-09-2026",
                },
                "end": {
                    "date": "2026-09-22",
                },
            },
            "YYYY-MM-DD",
        ),
        (
            {
                "summary": "Mixed boundary types",
                "start": {
                    "date": "2026-09-21",
                },
                "end": {
                    "dateTime": (
                        "2026-09-21T16:00:00+05:00"
                    )
                },
            },
            "both use date or both use dateTime",
        ),
    ],
)
def test_event_validation_rejects_malformed_payloads(
    event,
    match,
):
    service, oauth = build_service()

    with pytest.raises(
        ValueError,
        match=match,
    ):
        service.create_event(
            user_id="user-001",
            event=event,
        )

    assert oauth.access_token_calls == []


@pytest.mark.parametrize(
    "start,end",
    [
        (
            "2026-09-21T16:00:00+05:00",
            "2026-09-21T15:00:00+05:00",
        ),
        (
            "2026-09-21T15:00:00+05:00",
            "2026-09-21T15:00:00+05:00",
        ),
    ],
)
def test_event_validation_requires_end_after_start(
    start,
    end,
):
    service, oauth = build_service()

    with pytest.raises(
        ValueError,
        match="end must be after start",
    ):
        service.create_event(
            user_id="user-001",
            event=timed_event(
                start=start,
                end=end,
            ),
        )

    assert oauth.access_token_calls == []


def test_all_day_event_payload_is_valid():
    service, _oauth = build_service()

    payload = service._validate_event_payload(
        all_day_event()
    )

    assert payload == all_day_event()


def test_timed_event_requires_timezone():
    service, oauth = build_service()

    with pytest.raises(
        ValueError,
        match="timezone offset",
    ):
        service.create_event(
            user_id="user-001",
            event=timed_event(
                start="2026-09-21T15:00:00",
            ),
        )

    assert oauth.access_token_calls == []


def test_attendees_are_validated_before_provider_execution():
    service, oauth = build_service()

    invalid_attendee_event = {
        **timed_event(),
        "attendees": [
            {
                "email": "not-an-email",
            }
        ],
    }

    with pytest.raises(
        ValueError,
        match="invalid email",
    ):
        service.create_event(
            user_id="user-001",
            event=invalid_attendee_event,
        )

    assert oauth.access_token_calls == []


@pytest.mark.parametrize(
    "attendees,match",
    [
        (
            "user@example.com",
            "attendees must be a list",
        ),
        (
            [
                {
                    "displayName": "Missing email",
                }
            ],
            "must include an email",
        ),
        (
            [
                {
                    "email": "user@example.com",
                    "optional": "yes",
                }
            ],
            "optional must be a boolean",
        ),
        (
            [
                {
                    "email": "user@example.com",
                    "unexpected": True,
                }
            ],
            "unsupported fields",
        ),
    ],
)
def test_attendee_shape_is_deterministically_rejected(
    attendees,
    match,
):
    service, oauth = build_service()

    event = {
        **timed_event(),
        "attendees": attendees,
    }

    with pytest.raises(
        ValueError,
        match=match,
    ):
        service.create_event(
            user_id="user-001",
            event=event,
        )

    assert oauth.access_token_calls == []


def test_valid_attendees_are_preserved():
    service, _oauth = build_service()

    attendees = [
        {
            "email": "client@example.com",
            "displayName": "Client",
            "optional": False,
        }
    ]

    event = {
        **timed_event(),
        "attendees": attendees,
    }

    payload = service._validate_event_payload(
        event
    )

    assert payload["attendees"] == attendees


def test_update_event_applies_same_validation_to_changed_time():
    service, oauth = build_service()

    with pytest.raises(
        ValueError,
        match="valid ISO 8601 timestamp",
    ):
        service.update_event(
            user_id="user-001",
            event_id="event-001",
            event={
                "start": {
                    "dateTime": "tomorrow at 3 PM",
                },
                "end": {
                    "dateTime": (
                        "2026-09-21T16:00:00+05:00"
                    ),
                },
            },
        )

    assert oauth.access_token_calls == []


def test_list_filter_datetime_must_be_timezone_aware():
    service, oauth = build_service()

    with pytest.raises(
        ValueError,
        match="timezone offset",
    ):
        service.list_events(
            user_id="user-001",
            time_min="2026-09-21T00:00:00",
        )

    assert oauth.access_token_calls == []


def test_tool_adapter_requires_event_id_for_update():
    class FakeCalendarService:
        def update_event(self, **_kwargs):
            raise AssertionError(
                "provider must not be called"
            )

    adapter = GoogleCalendarToolService(
        calendar_service=FakeCalendarService()
    )

    result = adapter.execute(
        user_id="user-001",
        data={
            "calendar_action": "update",
            "event": {
                "summary": "Renamed",
            },
        },
    )

    assert result == {
        "success": False,
        "tool": "calendar",
        "action": "update",
        "result": None,
        "error": "event_id is required.",
    }


def test_graph_tool_node_executes_permitted_calendar_plan(
    monkeypatch,
):
    captured = {}

    def fake_execute(
        *,
        intent,
        user_id,
        data,
    ):
        captured["intent"] = intent
        captured["user_id"] = user_id
        captured["data"] = data

        return {
            "success": True,
            "tool": "calendar",
            "action": "create",
            "result": {
                "event_id": "event-001",
            },
            "error": None,
        }

    monkeypatch.setattr(
        graph.tool_router,
        "execute",
        fake_execute,
    )

    plan_data = {
        "calendar_action": "create",
        "event": timed_event(),
    }

    state = {
        "user_id": "user-001",
        "plan": {
            "requires_tool": True,
            "execution_mode": "single",
            "tool": "calendar",
            "action": "create",
            "data": plan_data,
        },
        "permission": {
            "allowed": True,
            "requires_confirmation": False,
            "reason": "Permitted.",
        },
        "confirmation": {
            "id": None,
            "status": None,
            "tool": None,
            "action": None,
            "reason": None,
        },
    }

    result = graph.tool_node(state)

    assert captured == {
        "intent": "calendar",
        "user_id": "user-001",
        "data": plan_data,
    }

    assert result["tool_result"] == {
        "success": True,
        "tool": "calendar",
        "action": "create",
        "result": {
            "event_id": "event-001",
        },
        "error": None,
    }


def test_graph_tool_node_does_not_execute_denied_calendar_plan(
    monkeypatch,
):
    executed = []

    def fake_execute(**_kwargs):
        executed.append(True)
        return {
            "success": True,
        }

    monkeypatch.setattr(
        graph.tool_router,
        "execute",
        fake_execute,
    )

    state = {
        "user_id": "user-001",
        "plan": {
            "requires_tool": True,
            "execution_mode": "single",
            "tool": "calendar",
            "action": "create",
            "data": {
                "calendar_action": "create",
                "event": timed_event(),
            },
        },
        "permission": {
            "allowed": False,
            "requires_confirmation": True,
            "reason": "Confirmation required.",
        },
        "confirmation": {
            "id": "confirmation-001",
            "status": "pending",
            "tool": "calendar",
            "action": "create",
            "reason": "Confirmation required.",
        },
    }

    result = graph.tool_node(state)

    assert executed == []
    assert result["tool_result"]["success"] is False
    assert result["tool_result"]["tool"] == "calendar"
    assert result["tool_result"]["action"] == "create"
    assert (
        result["tool_result"]["error"]
        == "Confirmation required."
    )
