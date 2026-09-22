from __future__ import annotations

from services.conversation_execution_service import (
    ConversationExecutionService,
)
from services.execution_context import (
    ExecutionContext,
)
from services.execution_service import (
    NOVAExecutionService,
)


def _agent_state():
    return {
        "user_id": "user-001",
        "conversation_id": 42,
        "user_message": "Hello NOVA",
        "history": [],
        "understanding": {},
        "plan": {},
        "permission": {
            "allowed": False,
            "requires_confirmation": False,
            "reason": "No permission check was performed.",
        },
        "user_requested": True,
        "execution_context": ExecutionContext.interactive(),
        "confirmation": {
            "id": None,
            "status": None,
            "tool": None,
            "action": None,
            "reason": None,
        },
        "tool_result": {
            "success": False,
            "tool": None,
            "action": None,
            "result": None,
            "error": None,
        },
        "workflow_result": {
            "success": False,
            "status": None,
            "workflow_id": None,
            "scheduled_at": None,
            "steps": [],
            "error": None,
        },
        "memory_context": "",
        "response": "",
    }


def test_agent_node_streams_response_deltas_through_callback(monkeypatch):
    from agent import graph

    deltas = []
    prompts = []

    def fake_generate_response_stream(prompt):
        prompts.append(prompt)
        yield "Hello"
        yield ", "
        yield "world"

    monkeypatch.setattr(
        graph.llm_service,
        "generate_response_stream",
        fake_generate_response_stream,
    )

    monkeypatch.setattr(
        graph,
        "_get_knowledge_retrieval",
        lambda _state: (
            "No relevant knowledge from NOVA's knowledge base was found.",
            [],
        ),
    )

    state = _agent_state()
    state["response_delta_callback"] = deltas.append

    result = graph.agent_node(state)

    assert result["response"] == "Hello, world"
    assert deltas == [
        "Hello",
        ", ",
        "world",
    ]
    assert prompts
    assert "Hello NOVA" in prompts[0]


def test_agent_node_callback_failure_does_not_change_authoritative_response(
    monkeypatch,
):
    from agent import graph

    deltas = []

    def fake_generate_response_stream(_prompt):
        yield "Reliable"
        yield " response"

    def failing_callback(delta):
        deltas.append(delta)
        raise RuntimeError("transport output failed")

    monkeypatch.setattr(
        graph.llm_service,
        "generate_response_stream",
        fake_generate_response_stream,
    )

    monkeypatch.setattr(
        graph,
        "_get_knowledge_retrieval",
        lambda _state: (
            "No relevant knowledge from NOVA's knowledge base was found.",
            [],
        ),
    )

    state = _agent_state()
    state["response_delta_callback"] = failing_callback

    result = graph.agent_node(state)

    assert result["response"] == "Reliable response"
    assert deltas == [
        "Reliable",
        " response",
    ]


class _FakeAgentGraph:
    def __init__(self):
        self.calls = []

    def invoke(self, state):
        self.calls.append(state)
        return {
            **state,
            "response": "Graph response.",
        }


def test_execution_service_propagates_response_delta_callback():
    graph = _FakeAgentGraph()
    service = NOVAExecutionService(graph)
    deltas = []
    callback = deltas.append

    result = service.execute(
        user_id="user-001",
        conversation_id=42,
        user_message="Hello NOVA",
        history=[],
        execution_context=ExecutionContext.interactive(),
        on_response_delta=callback,
    )

    assert result["response"] == "Graph response."
    assert (
        graph.calls[0]["response_delta_callback"]
        is callback
    )


class _FakeConversationService:
    def __init__(self):
        self.history = [
            {
                "role": "user",
                "content": "Previous message",
            }
        ]
        self.saved_messages = []

    def get_or_create_conversation(
        self,
        *,
        user_id,
        conversation_id,
    ):
        return conversation_id or 42

    def get_context_history(
        self,
        *,
        user_id,
        conversation_id,
        max_messages,
        max_characters,
    ):
        return list(self.history)

    def update_conversation_title(
        self,
        *,
        conversation_id,
        user_id,
        title,
    ):
        raise AssertionError(
            "Existing conversations must not be retitled."
        )

    def save_message(
        self,
        *,
        user_id,
        conversation_id,
        role,
        content,
    ):
        self.saved_messages.append(
            (
                user_id,
                conversation_id,
                role,
                content,
            )
        )


class _FakeExecutionService:
    def __init__(self):
        self.calls = []

    def execute(
        self,
        *,
        user_id,
        conversation_id,
        user_message,
        history,
        execution_context,
        on_response_delta=None,
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "user_message": user_message,
                "history": history,
                "execution_context": execution_context,
                "on_response_delta": on_response_delta,
            }
        )

        return {
            "response": "NOVA response",
            "understanding": {
                "intent": "chat",
            },
            "plan": {
                "requires_tool": False,
            },
            "permission": {
                "allowed": False,
                "requires_confirmation": False,
            },
            "confirmation": {
                "id": None,
                "status": None,
            },
            "tool_result": {
                "success": False,
            },
            "workflow_result": {},
            "knowledge_sources": [],
            "web_sources": [],
        }


class _FakeLLMService:
    def extract_memory(self, message):
        return None


class _FakeMemoryService:
    pass


def test_conversation_execution_service_propagates_response_delta_callback():
    conversation = _FakeConversationService()
    execution = _FakeExecutionService()
    service = ConversationExecutionService(
        conversation_service=conversation,
        execution_service=execution,
        llm_service=_FakeLLMService(),
        memory_service=_FakeMemoryService(),
    )

    callback = lambda _delta: None

    result = service.execute_message(
        user_id="user-001",
        message="Hello NOVA",
        conversation_id=42,
        on_response_delta=callback,
    )

    assert result["response"] == "NOVA response"
    assert execution.calls[0]["on_response_delta"] is callback
