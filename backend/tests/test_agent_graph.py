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