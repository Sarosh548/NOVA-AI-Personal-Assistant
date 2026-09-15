from agent.graph import (
    memory_node,
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


def test_route_task_to_tool():
    state = {
        "understanding": {
            "intent": "task",
            "requires_tool": True,
        }
    }

    assert (
        route_after_understanding(state)
        == "tool"
    )


def test_route_reminder_to_tool():
    state = {
        "understanding": {
            "intent": "reminder",
            "requires_tool": True,
        }
    }

    assert (
        route_after_understanding(state)
        == "tool"
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

    assert fake_service.received_history == []