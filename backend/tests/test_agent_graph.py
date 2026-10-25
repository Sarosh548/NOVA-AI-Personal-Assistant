from types import SimpleNamespace

from agent.graph import (
    memory_node,
    permission_node,
    planner_node,
    route_after_permission,
    route_after_understanding,
    understanding_node,
)


class FakeMemoryService:

    def __init__(
        self,
        semantic_memories=None,
        profile_memories=None,
    ):
        self.semantic_memories = (
            semantic_memories or []
        )
        self.profile_memories = (
            profile_memories or []
        )

    def find_similar_memories(
        self,
        user_id,
        new_memory,
        threshold,
        limit,
    ):
        return self.semantic_memories

    def get_profile_memories(
        self,
        user_id,
        limit,
    ):
        return self.profile_memories


class FakeIntentService:

    def __init__(self):
        self.received_message = None
        self.received_history = None

    def analyze(
        self,
        message,
        history=None,
    ):
        self.received_message = message
        self.received_history = history

        return {
            "intent": "task",
            "task": None,
            "task_reference": (
                "practice LangGraph"
            ),
            "task_action": "complete",
            "task_id": None,
            "priority": None,
            "time": None,
            "scheduled_at": None,
            "emotion": "neutral",
            "tone": "neutral",
            "visual": "none",
            "action": None,
            "requires_tool": True,
        }


class FakeToolMetadataRouter:

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


def test_memory_node_uses_semantic_memories_when_available(
    monkeypatch,
):
    fake_service = FakeMemoryService(
        semantic_memories=[
            {
                "memory": "User prefers Python.",
                "category": "preference",
                "importance": "medium",
            }
        ]
    )

    monkeypatch.setattr(
        "agent.graph.memory_service",
        fake_service,
    )

    result = memory_node(
        {
            "user_message": (
                "What programming language do I prefer?"
            ),
            "memory_context": "",
            "response": "",
        }
    )

    assert (
        "User prefers Python."
        in result["memory_context"]
    )


def test_memory_node_falls_back_to_profile_memories(
    monkeypatch,
):
    fake_service = FakeMemoryService(
        semantic_memories=[],
        profile_memories=[
            {
                "memory": "Sarosh is building NOVA.",
                "category": "personal",
                "importance": "medium",
            },
            {
                "memory": "User prefers Python.",
                "category": "preference",
                "importance": "medium",
            },
        ],
    )

    monkeypatch.setattr(
        "agent.graph.memory_service",
        fake_service,
    )

    result = memory_node(
        {
            "user_message": (
                "Tell me what you remember about me."
            ),
            "memory_context": "",
            "response": "",
        }
    )

    assert (
        "Sarosh is building NOVA."
        in result["memory_context"]
    )

    assert (
        "User prefers Python."
        in result["memory_context"]
    )


def test_memory_node_returns_empty_message_when_no_memory(
    monkeypatch,
):
    fake_service = FakeMemoryService()

    monkeypatch.setattr(
        "agent.graph.memory_service",
        fake_service,
    )

    result = memory_node(
        {
            "user_message": "Hello NOVA",
            "memory_context": "",
            "response": "",
        }
    )

    assert (
        result["memory_context"]
        == "No relevant long-term memory found."
    )


def test_route_normal_chat_directly_to_agent():
    state = {
        "understanding": {
            "intent": "chat",
            "requires_tool": False,
        }
    }

    assert (
        route_after_understanding(state)
        == "agent"
    )


def test_task_plan_passes_through_permission_to_tool(
    monkeypatch,
):
    fake_router = FakeToolMetadataRouter()

    monkeypatch.setattr(
        "agent.graph.tool_router",
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
            "task": "Practice Python",
            "task_reference": None,
            "task_action": "create",
            "task_id": None,
            "priority": "high",
            "time": None,
            "scheduled_at": None,
            "action": None,
            "requires_tool": True,
        },
        "plan": {},
        "permission": {},
        "user_requested": True,
        "tool_result": {},
        "memory_context": "",
        "response": "",
    }

    planned_state = planner_node(state)

    assert (
        planned_state["plan"]["requires_tool"]
        is True
    )

    assert (
        planned_state["plan"]["tool"]
        == "task"
    )

    assert (
        planned_state["plan"]["action"]
        == "create"
    )

    permission_state = permission_node(
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

    route = route_after_permission(
        permission_state
    )

    assert route == "tool"


def test_reminder_plan_passes_through_permission_to_tool(
    monkeypatch,
):
    fake_router = FakeToolMetadataRouter()

    monkeypatch.setattr(
        "agent.graph.tool_router",
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
            "task": "Call HR",
            "task_reference": None,
            "task_action": None,
            "task_id": None,
            "priority": None,
            "time": "tomorrow",
            "scheduled_at": (
                "2026-09-18T10:00:00+05:00"
            ),
            "reminder_action": "create",
            "reminder_reference": None,
            "reminder_id": None,
            "action": None,
            "requires_tool": True,
        },
        "plan": {},
        "permission": {},
        "user_requested": True,
        "tool_result": {},
        "memory_context": "",
        "response": "",
    }

    planned_state = planner_node(state)

    assert (
        planned_state["plan"]["requires_tool"]
        is True
    )

    assert (
        planned_state["plan"]["tool"]
        == "reminder"
    )

    assert (
        planned_state["plan"]["action"]
        == "create"
    )

    permission_state = permission_node(
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

    route = route_after_permission(
        permission_state
    )

    assert route == "tool"


def test_confirmation_required_action_routes_to_agent():
    state = {
        "plan": {
            "requires_tool": True,
            "tool": "task",
            "action": "delete",
        },
        "permission": {
            "allowed": False,
            "requires_confirmation": True,
            "reason": (
                "Confirmation required."
            ),
        },
    }

    assert (
        route_after_permission(state)
        == "agent"
    )


def test_understanding_node_receives_conversation_history(
    monkeypatch,
):
    fake_service = FakeIntentService()

    monkeypatch.setattr(
        "agent.graph.intent_service",
        fake_service,
    )

    history = [
        {
            "role": "user",
            "content": (
                "Create a task to practice LangGraph."
            ),
        },
        {
            "role": "assistant",
            "content": (
                "Done. I created the task."
            ),
        },
    ]

    result = understanding_node(
        {
            "user_message": "Complete it.",
            "history": history,
            "understanding": {},
            "tool_result": {},
            "memory_context": "",
            "response": "",
        }
    )

    assert (
        fake_service.received_message
        == "Complete it."
    )

    assert (
        fake_service.received_history
        == history
    )

    assert (
        result["understanding"]["task_reference"]
        == "practice LangGraph"
    )


def test_understanding_node_handles_missing_history(
    monkeypatch,
):
    fake_service = FakeIntentService()

    monkeypatch.setattr(
        "agent.graph.intent_service",
        fake_service,
    )

    understanding_node(
        {
            "user_message": "Hello NOVA",
            "understanding": {},
            "tool_result": {},
            "memory_context": "",
            "response": "",
        }
    )

    assert (
        fake_service.received_history
        == []
    )

def test_permission_node_snapshots_exact_pending_task_ids_before_confirmation(monkeypatch):
    import agent.graph as graph

    selected = [
        {"id": 219, "title": "Nova test B", "priority": "high", "status": "pending", "due_at": None},
        {"id": 218, "title": "Nova test B", "priority": "medium", "status": "pending", "due_at": None},
        {"id": 217, "title": "Nova Test A Basic", "priority": "low", "status": "pending", "due_at": None},
        {"id": 216, "title": "named Nova test", "priority": "medium", "status": "pending", "due_at": None},
        {"id": 215, "title": "lower test a basic", "priority": "medium", "status": "pending", "due_at": None},
        {"id": 214, "title": 'with the exact title "lower test a basic', "priority": "medium", "status": "pending", "due_at": None},
    ]

    class FakeTaskService:
        def __init__(self):
            self.requested_status = None

        def get_tasks(self, *, user_id, status=None):
            self.requested_status = status
            return [task for task in selected if status is None or task["status"] == status]

    class FakeToolRouter:
        def __init__(self):
            self.task_service = FakeTaskService()

    class FakePermissionService:
        def check(self, **kwargs):
            return SimpleNamespace(
                allowed=False,
                requires_confirmation=True,
                reason="Task deletion requires explicit confirmation.",
            )

    class FakeConfirmationService:
        def __init__(self):
            self.created = []

        def create_confirmation(self, **kwargs):
            self.created.append(kwargs)
            return 901

    router = FakeToolRouter()
    confirmations = FakeConfirmationService()
    monkeypatch.setattr(graph, "tool_router", router)
    monkeypatch.setattr(graph, "permission_service", FakePermissionService())
    monkeypatch.setattr(graph, "confirmation_service", confirmations)

    state = {
        "user_id": "test-user",
        "conversation_id": 394,
        "user_requested": True,
        "plan": {
            "requires_tool": True,
            "tool": "task",
            "action": "delete",
            "data": {
                "intent": "task",
                "task_action": "delete",
                "task_reference": None,
                "bulk_task_delete": True,
                "task_status_filter": "pending",
            },
            "steps": [],
        },
    }

    result = graph.permission_node(state)

    assert result["confirmation"]["status"] == "pending"
    assert router.task_service.requested_status == "pending"
    assert len(confirmations.created) == 1

    saved = confirmations.created[0]
    assert "expires_in_seconds" not in saved
    assert saved["data"]["task_ids"] == [219, 218, 217, 216, 215, 214]
    assert [task["title"] for task in saved["data"]["task_snapshot"]] == [
        task["title"] for task in selected
    ]
    assert "6 task(s)" in saved["reason"]
    assert '#219 "Nova test B"' in saved["reason"]
    assert '#214 "with the exact title "lower test a basic"' in saved["reason"]

def test_permission_node_exposes_email_draft_preview_without_mutating_saved_confirmation(monkeypatch):
    import agent.graph as graph

    class FakeNotificationService:
        def resolve_self_email_destination(self, *, user_id):
            assert user_id == "test-user"
            return "owner@example.com"

    class FakeToolRouter:
        notification_service = FakeNotificationService()

    class FakePermissionService:
        def check(self, **kwargs):
            assert kwargs["tool"] == "email"
            assert kwargs["action"] == "send"
            return SimpleNamespace(
                allowed=False,
                requires_confirmation=True,
                reason="External email requires explicit confirmation.",
            )

    class FakeConfirmationService:
        def __init__(self):
            self.created = []

        def create_confirmation(self, **kwargs):
            self.created.append(kwargs)
            return 902

    confirmations = FakeConfirmationService()
    monkeypatch.setattr(graph, "tool_router", FakeToolRouter())
    monkeypatch.setattr(graph, "permission_service", FakePermissionService())
    monkeypatch.setattr(graph, "confirmation_service", confirmations)

    email_data = {
        "intent": "email",
        "email_action": "send",
        "recipient_reference": "self",
        "to": None,
        "cc": ["copy@example.com"],
        "bcc": None,
        "subject": "Project update",
        "body": "The project is on track.",
    }
    result = graph.permission_node({
        "user_id": "test-user",
        "conversation_id": 395,
        "execution_context": graph.ExecutionContext.interactive(),
        "plan": {
            "requires_tool": True,
            "tool": "email",
            "action": "send",
            "data": email_data,
            "steps": [],
        },
    })

    assert result["permission"]["requires_confirmation"] is True
    assert result["confirmation"]["status"] == "pending"
    assert result["confirmation"]["preview"] == {
        "kind": "email",
        "to": "owner@example.com",
        "cc": ["copy@example.com"],
        "bcc": None,
        "subject": "Project update",
        "body": "The project is on track.",
    }
    assert len(confirmations.created) == 1
    assert confirmations.created[0]["expires_in_seconds"] == graph.EMAIL_SEND_CONFIRMATION_TTL_SECONDS
    assert "preview" not in confirmations.created[0]["data"]
    assert confirmations.created[0]["data"]["body"] == "The project is on track."
