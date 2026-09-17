from agent import graph


class FakeToolRouter:
    """
    Safe in-memory router for permission integration tests.
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
                    "complete",
                    "delete",
                ],
            }
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
                or data.get("action")
            ),
            "result": {
                "message": "fake execution successful",
            },
            "error": None,
        }


class FakeConfirmationService:
    """
    Safe in-memory confirmation service.
    """

    def __init__(self):
        self.created_calls = []

    def create_confirmation(
        self,
        user_id,
        conversation_id,
        tool,
        action,
        data,
        reason,
    ):
        self.created_calls.append(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "tool": tool,
                "action": action,
                "data": data,
                "reason": reason,
            }
        )

        return 501


def test_permission_node_allows_explicit_user_request():
    state = {
        "user_id": "user-001",
        "conversation_id": None,
        "user_message": (
            "Create a task to practice Python"
        ),
        "history": [],
        "understanding": {},
        "plan": {
            "requires_tool": True,
            "tool": "task",
            "action": "create",
            "data": {
                "task_action": "create",
                "task": "Practice Python",
            },
            "reason": "Task tool is available.",
        },
        "permission": {},
        "user_requested": True,
        "confirmation": {},
        "tool_result": {},
        "memory_context": "",
        "response": "",
    }

    result = graph.permission_node(state)

    assert result["permission"]["allowed"] is True

    assert (
        result["permission"]
        ["requires_confirmation"]
        is False
    )

    assert (
        result["confirmation"]["id"]
        is None
    )


def test_permission_node_creates_confirmation_for_background_action(
    monkeypatch,
):
    fake_confirmation_service = (
        FakeConfirmationService()
    )

    monkeypatch.setattr(
        graph,
        "confirmation_service",
        fake_confirmation_service,
    )

    state = {
        "user_id": "user-001",
        "conversation_id": 42,
        "user_message": "Background task action",
        "history": [],
        "understanding": {},
        "plan": {
            "requires_tool": True,
            "tool": "task",
            "action": "delete",
            "data": {
                "task_action": "delete",
                "task_reference": "Old task",
            },
            "reason": "Task tool is available.",
        },
        "permission": {},
        "user_requested": False,
        "confirmation": {},
        "tool_result": {},
        "memory_context": "",
        "response": "",
    }

    result = graph.permission_node(state)

    assert result["permission"]["allowed"] is False

    assert (
        result["permission"]
        ["requires_confirmation"]
        is True
    )

    assert result["confirmation"]["id"] == 501
    assert result["confirmation"]["status"] == "pending"
    assert result["confirmation"]["tool"] == "task"
    assert result["confirmation"]["action"] == "delete"

    assert len(
        fake_confirmation_service.created_calls
    ) == 1

    created = (
        fake_confirmation_service.created_calls[0]
    )

    assert created["user_id"] == "user-001"
    assert created["conversation_id"] == 42
    assert created["tool"] == "task"
    assert created["action"] == "delete"
    assert (
        created["data"]["task_reference"]
        == "Old task"
    )


def test_permission_route_allows_only_permitted_tool():
    state = {
        "plan": {
            "requires_tool": True,
            "tool": "task",
            "action": "create",
        },
        "permission": {
            "allowed": True,
            "requires_confirmation": False,
            "reason": "Allowed.",
        },
    }

    route = graph.route_after_permission(state)

    assert route == "tool"


def test_permission_route_blocks_confirmation_required_action():
    state = {
        "plan": {
            "requires_tool": True,
            "tool": "task",
            "action": "delete",
        },
        "permission": {
            "allowed": False,
            "requires_confirmation": True,
            "reason": "Confirmation required.",
        },
    }

    route = graph.route_after_permission(state)

    assert route == "agent"


def test_permission_route_blocks_denied_action():
    state = {
        "plan": {
            "requires_tool": True,
            "tool": "task",
            "action": "unknown",
        },
        "permission": {
            "allowed": False,
            "requires_confirmation": False,
            "reason": "Denied.",
        },
    }

    route = graph.route_after_permission(state)

    assert route == "agent"


def test_disallowed_tool_cannot_execute(
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
        "user_message": "Background action",
        "history": [],
        "understanding": {},
        "plan": {
            "requires_tool": True,
            "tool": "task",
            "action": "delete",
            "data": {
                "task_action": "delete",
            },
            "reason": "Task tool is available.",
        },
        "permission": {
            "allowed": False,
            "requires_confirmation": True,
            "reason": (
                "Action 'delete' on tool 'task' "
                "requires confirmation."
            ),
        },
        "user_requested": False,
        "confirmation": {
            "id": 501,
            "status": "pending",
            "tool": "task",
            "action": "delete",
            "reason": "Confirmation required.",
        },
        "tool_result": {},
        "memory_context": "",
        "response": "",
    }

    result = graph.tool_node(state)

    assert result["tool_result"]["success"] is False

    assert (
        result["tool_result"]["tool"]
        == "task"
    )

    assert (
        result["tool_result"]["action"]
        == "delete"
    )

    assert "requires confirmation" in (
        result["tool_result"]["error"]
    )

    assert fake_router.executed_calls == []