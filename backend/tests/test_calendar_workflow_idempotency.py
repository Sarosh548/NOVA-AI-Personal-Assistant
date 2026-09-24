from services.durable_workflow_execution_service import (
    DurableWorkflowExecutionService,
)
from services.google_calendar_tool_service import (
    GoogleCalendarToolService,
)


class FakeCalendarService:
    DEFAULT_MAX_RESULTS = 50

    def __init__(self):
        self.calls = []

    def create_event(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {
            "id": "evt-001",
            "summary": kwargs["event"]["summary"],
        }


class FakeToolRouter:
    def __init__(self):
        self.calls = []

    def execute(
        self,
        *,
        intent,
        user_id,
        data,
    ):
        self.calls.append(
            {
                "intent": intent,
                "user_id": user_id,
                "data": dict(data),
            }
        )

        return {
            "success": True,
            "result": {
                "event_id": "evt-001",
            },
            "error": None,
        }


def timed_event():
    return {
        "summary": "Workflow meeting",
        "start": {
            "dateTime": "2026-09-24T15:00:00+05:00",
        },
        "end": {
            "dateTime": "2026-09-24T16:00:00+05:00",
        },
    }


def test_calendar_tool_forwards_idempotency_key():
    calendar_service = FakeCalendarService()
    tool_service = GoogleCalendarToolService(
        calendar_service=calendar_service
    )

    result = tool_service.execute(
        user_id="user-001",
        data={
            "calendar_action": "create",
            "event": timed_event(),
            "idempotency_key": "workflow:42:step:step-1",
        },
    )

    assert result["success"] is True
    assert result["result"]["event_id"] == "evt-001"

    assert calendar_service.calls == [
        {
            "user_id": "user-001",
            "event": timed_event(),
            "calendar_id": None,
            "send_updates": "all",
            "idempotency_key": "workflow:42:step:step-1",
        }
    ]


def test_durable_calendar_create_gets_stable_workflow_idempotency_key():
    tool_router = FakeToolRouter()
    execution_service = DurableWorkflowExecutionService(
        tool_router=tool_router
    )

    step = {
        "workflow_id": 42,
        "step_id": "step-1",
        "tool": "calendar",
        "action": "create",
        "data": {
            "calendar_action": "create",
            "event": timed_event(),
        },
    }

    first = execution_service._execute_step(
        user_id="user-001",
        step=step,
    )
    second = execution_service._execute_step(
        user_id="user-001",
        step=step,
    )

    assert first["success"] is True
    assert second["success"] is True

    assert len(tool_router.calls) == 2

    first_data = tool_router.calls[0]["data"]
    second_data = tool_router.calls[1]["data"]

    assert first_data["idempotency_key"] == (
        "workflow:42:step:step-1"
    )
    assert second_data["idempotency_key"] == (
        "workflow:42:step:step-1"
    )
    assert first_data["idempotency_key"] == (
        second_data["idempotency_key"]
    )

    assert "idempotency_key" not in step["data"]


def test_durable_calendar_create_preserves_existing_idempotency_key():
    tool_router = FakeToolRouter()
    execution_service = DurableWorkflowExecutionService(
        tool_router=tool_router
    )

    step = {
        "workflow_id": 42,
        "step_id": "step-2",
        "tool": "calendar",
        "action": "create",
        "data": {
            "calendar_action": "create",
            "event": timed_event(),
            "idempotency_key": "caller-supplied-key",
        },
    }

    result = execution_service._execute_step(
        user_id="user-001",
        step=step,
    )

    assert result["success"] is True
    assert tool_router.calls[0]["data"]["idempotency_key"] == (
        "caller-supplied-key"
    )
