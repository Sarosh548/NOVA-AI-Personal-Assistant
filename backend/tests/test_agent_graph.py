from agent.graph import (
    memory_node,
    route_after_understanding,
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