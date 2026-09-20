from services.google_calendar_tool_service import (
    GoogleCalendarToolService,
)
from services.permission_service import PermissionService
from services.risk_policy_service import (
    RiskLevel,
    RiskPolicyService,
)
from services.tool_router import ToolRouter


class FakeCalendarService:
    DEFAULT_MAX_RESULTS = 50

    def __init__(self):
        self.calls = []

    def list_events(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {
            "events": [
                {
                    "id": "evt-1",
                    "summary": "Private meeting",
                }
            ],
            "next_page_token": None,
            "next_sync_token": None,
        }

    def get_event(self, **kwargs):
        self.calls.append(("get", kwargs))
        return {
            "id": kwargs["event_id"],
            "summary": "Private meeting",
            "description": "Do not persist this.",
        }

    def create_event(self, **kwargs):
        self.calls.append(("create", kwargs))
        return {
            "id": "evt-1",
            "summary": "Private meeting",
            "description": "Do not persist this.",
        }

    def update_event(self, **kwargs):
        self.calls.append(("update", kwargs))
        return {
            "id": kwargs["event_id"],
            "summary": "Updated private meeting",
            "description": "Do not persist this.",
        }

    def delete_event(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return {
            "deleted": True,
            "event_id": kwargs["event_id"],
        }


class FakeActivityEventService:
    def __init__(self):
        self.events = []

    def record_event(self, **kwargs):
        self.events.append(kwargs)


def test_calendar_adapter_dispatches_list_action():
    calendar_service = FakeCalendarService()
    adapter = GoogleCalendarToolService(
        calendar_service=calendar_service
    )

    result = adapter.execute(
        user_id="user-001",
        data={
            "calendar_action": "list",
            "time_min": "2026-09-20T09:00:00+05:00",
            "time_max": "2026-09-20T18:00:00+05:00",
            "query": "AI interview",
            "max_results": 10,
        },
    )

    assert result["success"] is True
    assert result["tool"] == "calendar"
    assert result["action"] == "list"
    assert result["result"]["events"][0]["id"] == "evt-1"

    assert calendar_service.calls == [
        (
            "list",
            {
                "user_id": "user-001",
                "calendar_id": None,
                "time_min": "2026-09-20T09:00:00+05:00",
                "time_max": "2026-09-20T18:00:00+05:00",
                "query": "AI interview",
                "max_results": 10,
                "page_token": None,
                "single_events": True,
                "order_by": "startTime",
                "show_deleted": False,
            },
        )
    ]


def test_calendar_adapter_normalizes_event_id():
    calendar_service = FakeCalendarService()
    adapter = GoogleCalendarToolService(
        calendar_service=calendar_service
    )

    result = adapter.execute(
        user_id="user-001",
        data={
            "calendar_action": "create",
            "event": {
                "summary": "Private meeting",
                "start": {
                    "dateTime": "2026-09-20T12:00:00+05:00",
                },
                "end": {
                    "dateTime": "2026-09-20T13:00:00+05:00",
                },
            },
        },
    )

    assert result["success"] is True
    assert result["result"]["event_id"] == "evt-1"
    assert result["result"]["summary"] == "Private meeting"


def test_tool_router_registers_calendar_only_when_injected():
    calendar_service = FakeCalendarService()
    router = ToolRouter(
        calendar_tool_service=GoogleCalendarToolService(
            calendar_service=calendar_service
        )
    )

    tools = router.get_available_tools()

    assert tools[-1] == {
        "name": "calendar",
        "description": (
            "List, retrieve, create, update, and delete "
            "Google Calendar events."
        ),
        "actions": [
            "list",
            "get",
            "create",
            "update",
            "delete",
        ],
    }


def test_tool_router_executes_calendar_and_logs_safe_activity():
    calendar_service = FakeCalendarService()
    activity_service = FakeActivityEventService()

    router = ToolRouter(
        activity_event_service=activity_service,
        calendar_tool_service=GoogleCalendarToolService(
            calendar_service=calendar_service
        ),
    )

    result = router.execute(
        intent="calendar",
        user_id="user-001",
        data={
            "calendar_action": "create",
            "event": {
                "summary": "Private meeting",
                "description": "Sensitive event notes.",
                "start": {
                    "dateTime": "2026-09-20T12:00:00+05:00",
                },
                "end": {
                    "dateTime": "2026-09-20T13:00:00+05:00",
                },
            },
        },
    )

    assert result["success"] is True
    assert result["tool"] == "calendar"
    assert result["action"] == "create"
    assert result["result"]["event_id"] == "evt-1"

    assert len(activity_service.events) == 1

    event = activity_service.events[0]

    assert event["event_type"] == "calendar_create"
    assert event["status"] == "success"
    assert event["title"] == (
        "Calendar event created (ID evt-1)"
    )
    assert event["summary"] == (
        "Calendar event action 'create' succeeded "
        "for ID evt-1."
    )
    assert event["metadata"] == {
        "tool": "calendar",
        "action": "create",
        "entity_id": "evt-1",
    }

    serialized_activity = repr(event)

    assert "Private meeting" not in serialized_activity
    assert "Sensitive event notes." not in serialized_activity


def test_calendar_list_is_low_risk():
    service = RiskPolicyService()

    result = service.assess(
        tool="calendar",
        action="list",
        data={},
    )

    assert result.level == RiskLevel.LOW.value
    assert result.flags == ()


def test_calendar_create_without_attendees_is_medium_risk():
    service = RiskPolicyService()

    result = service.assess(
        tool="calendar",
        action="create",
        data={
            "event": {
                "summary": "Private meeting",
                "start": {
                    "dateTime": "2026-09-20T12:00:00+05:00",
                },
                "end": {
                    "dateTime": "2026-09-20T13:00:00+05:00",
                },
            }
        },
    )

    assert result.level == RiskLevel.MEDIUM.value
    assert result.flags == ()


def test_calendar_delete_is_medium_risk():
    service = RiskPolicyService()

    result = service.assess(
        tool="calendar",
        action="delete",
        data={
            "event_id": "evt-1",
        },
    )

    assert result.level == RiskLevel.MEDIUM.value
    assert result.flags == ()


def test_calendar_create_with_attendees_is_high_risk():
    service = RiskPolicyService()

    result = service.assess(
        tool="calendar",
        action="create",
        data={
            "event": {
                "summary": "Client meeting",
                "start": {
                    "dateTime": "2026-09-20T12:00:00+05:00",
                },
                "end": {
                    "dateTime": "2026-09-20T13:00:00+05:00",
                },
                "attendees": [
                    {
                        "email": "client@example.com",
                    }
                ],
            }
        },
    )

    assert result.level == RiskLevel.HIGH.value
    assert result.flags == (
        "external_communication",
    )


def test_calendar_create_with_empty_attendees_is_not_external_communication():
    service = RiskPolicyService()

    result = service.assess(
        tool="calendar",
        action="create",
        data={
            "event": {
                "summary": "Private meeting",
                "attendees": [],
            }
        },
    )

    assert result.level == RiskLevel.MEDIUM.value
    assert result.flags == ()


def test_calendar_attendee_action_requires_confirmation_even_interactive():
    service = PermissionService()

    decision = service.check(
        user_id="calendar-risk-interactive",
        tool="calendar",
        action="create",
        user_requested=True,
        data={
            "event": {
                "summary": "Client meeting",
                "attendees": [
                    {
                        "email": "client@example.com",
                    }
                ],
            }
        },
    )

    assert decision.allowed is False
    assert decision.requires_confirmation is True
    assert decision.risk_level == RiskLevel.HIGH.value
    assert "external_communication" in decision.risk_flags


def test_calendar_attendee_action_cannot_be_bypassed_by_saved_allow():
    service = PermissionService()
    user_id = "calendar-risk-saved-allow"

    try:
        service.set_permission(
            user_id=user_id,
            tool="calendar",
            action="create",
            mode="allow",
        )

        decision = service.check(
            user_id=user_id,
            tool="calendar",
            action="create",
            user_requested=False,
            data={
                "event": {
                    "summary": "Client meeting",
                    "attendees": [
                        {
                            "email": "client@example.com",
                        }
                    ],
                }
            },
        )

        assert decision.allowed is False
        assert decision.requires_confirmation is True
        assert decision.risk_level == RiskLevel.HIGH.value
        assert "external_communication" in decision.risk_flags

    finally:
        service.delete_permission(
            user_id=user_id,
            tool="calendar",
            action="create",
        )
