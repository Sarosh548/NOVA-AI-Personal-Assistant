from agent import graph


class FakeToolRouter:
    """
    Safe in-memory tool router for end-to-end planner tests.

    No database or real NOVA tools are executed.
    """

    def __init__(self):
        self.executed_calls = []

    def get_available_tools(self):
        return [
            {
                "name": "task",
                "description": "Manage tasks.",
                "actions": [
                    "create",
                    "list",
                    "start",
                    "complete",
                    "cancel",
                    "delete",
                    "update",
                ],
            },
            {
                "name": "reminder",
                "description": "Manage reminders.",
                "actions": [
                    "create",
                    "list",
                    "complete",
                    "cancel",
                    "delete",
                    "update",
                ],
            },
        ]

    def execute(
        self,
        intent,
        user_id,
        data=None,
    ):
        self.executed_calls.append(
            {
                "intent": intent,
                "user_id": user_id,
                "data": data,
            }
        )

        return {
            "success": True,
            "tool": intent,
            "action": (
                data.get("task_action")
                or data.get("reminder_action")
            ),
            "result": {
                "message": "fake execution successful",
            },
            "error": None,
        }


def test_planner_to_permission_to_tool_flow_for_task(
    monkeypatch,
):
    fake_router = FakeToolRouter()

    monkeypatch.setattr(
        graph,
        "tool_router",
        fake_router,
    )

    state = {
        "user_id": "user-001",
        "conversation_id": None,
        "user_message": (
            "Create a task to practice Python"
        ),
        "history": [],
        "understanding": {
            "intent": "task",
            "requires_tool": True,
            "task_action": "create",
            "task": "Practice Python",
            "priority": "high",
        },
        "plan": {},
        "permission": {},
        "user_requested": True,
        "tool_result": {
            "success": False,
            "tool": None,
            "action": None,
            "result": None,
            "error": None,
        },
        "memory_context": "",
        "response": "",
    }

    planned_state = graph.planner_node(state)

    assert planned_state["plan"]["requires_tool"] is True
    assert planned_state["plan"]["tool"] == "task"
    assert planned_state["plan"]["action"] == "create"

    permission_state = graph.permission_node(
        planned_state
    )

    assert permission_state["permission"]["allowed"] is True
    assert (
        permission_state["permission"]
        ["requires_confirmation"]
        is False
    )

    route = graph.route_after_permission(
        permission_state
    )

    assert route == "tool"

    executed_state = graph.tool_node(
        permission_state
    )

    assert (
        executed_state["tool_result"]["success"]
        is True
    )
    assert (
        executed_state["tool_result"]["tool"]
        == "task"
    )
    assert (
        executed_state["tool_result"]["action"]
        == "create"
    )

    assert len(fake_router.executed_calls) == 1

    call = fake_router.executed_calls[0]

    assert call["intent"] == "task"
    assert call["user_id"] == "user-001"
    assert call["data"]["task_action"] == "create"
    assert (
        call["data"]["task"]
        == "Practice Python"
    )


def test_planner_to_permission_to_tool_flow_for_reminder(
    monkeypatch,
):
    fake_router = FakeToolRouter()

    monkeypatch.setattr(
        graph,
        "tool_router",
        fake_router,
    )

    state = {
        "user_id": "user-001",
        "conversation_id": None,
        "user_message": (
            "Remind me tomorrow to call HR"
        ),
        "history": [],
        "understanding": {
            "intent": "reminder",
            "requires_tool": True,
            "reminder_action": "create",
            "task": "Call HR",
            "scheduled_at": (
                "2026-09-17T10:00:00+05:00"
            ),
        },
        "plan": {},
        "permission": {},
        "user_requested": True,
        "tool_result": {
            "success": False,
            "tool": None,
            "action": None,
            "result": None,
            "error": None,
        },
        "memory_context": "",
        "response": "",
    }

    planned_state = graph.planner_node(state)

    assert planned_state["plan"]["requires_tool"] is True
    assert (
        planned_state["plan"]["tool"]
        == "reminder"
    )
    assert (
        planned_state["plan"]["action"]
        == "create"
    )

    permission_state = graph.permission_node(
        planned_state
    )

    assert (
        permission_state["permission"]["allowed"]
        is True
    )
    assert (
        permission_state["permission"]
        ["requires_confirmation"]
        is False
    )

    route = graph.route_after_permission(
        permission_state
    )

    assert route == "tool"

    executed_state = graph.tool_node(
        permission_state
    )

    assert (
        executed_state["tool_result"]["success"]
        is True
    )
    assert (
        executed_state["tool_result"]["tool"]
        == "reminder"
    )
    assert (
        executed_state["tool_result"]["action"]
        == "create"
    )

    assert len(fake_router.executed_calls) == 1

    call = fake_router.executed_calls[0]

    assert call["intent"] == "reminder"
    assert call["user_id"] == "user-001"
    assert (
        call["data"]["reminder_action"]
        == "create"
    )
    assert call["data"]["task"] == "Call HR"


def test_normal_chat_does_not_enter_tool_flow(
    monkeypatch,
):
    fake_router = FakeToolRouter()

    monkeypatch.setattr(
        graph,
        "tool_router",
        fake_router,
    )

    state = {
        "user_id": "user-001",
        "conversation_id": None,
        "user_message": "Hello NOVA",
        "history": [],
        "understanding": {
            "intent": "chat",
            "requires_tool": False,
        },
        "plan": {},
        "permission": {},
        "user_requested": True,
        "tool_result": {
            "success": False,
            "tool": None,
            "action": None,
            "result": None,
            "error": None,
        },
        "memory_context": "",
        "response": "",
    }

    planned_state = graph.planner_node(state)

    assert (
        planned_state["plan"]["requires_tool"]
        is False
    )
    assert (
        planned_state["plan"]["tool"]
        is None
    )
    assert (
        planned_state["plan"]["action"]
        is None
    )

    permission_state = graph.permission_node(
        planned_state
    )

    assert (
        permission_state["permission"]["allowed"]
        is False
    )
    assert (
        permission_state["permission"]
        ["requires_confirmation"]
        is False
    )

    route = graph.route_after_permission(
        permission_state
    )

    assert route == "agent"

    executed_state = graph.tool_node(
        permission_state
    )

    assert (
        executed_state["tool_result"]["success"]
        is False
    )
    assert (
        executed_state["tool_result"]["tool"]
        is None
    )
    assert (
        executed_state["tool_result"]["action"]
        is None
    )

    assert fake_router.executed_calls == []