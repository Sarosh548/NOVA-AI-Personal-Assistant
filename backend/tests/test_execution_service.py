from services.execution_context import (
    ExecutionContext,
    ExecutionMode,
)
from services.execution_service import (
    NOVAExecutionService,
)


class FakeAgentGraph:
    def __init__(self):
        self.calls = []

    def invoke(self, state):
        self.calls.append(state)

        return {
            **state,
            "response": "Test response.",
        }


def test_interactive_execution_builds_interactive_state():
    graph = FakeAgentGraph()
    service = NOVAExecutionService(graph)

    result = service.execute(
        user_id="user-001",
        conversation_id=10,
        user_message="Hello NOVA",
        history=[],
        execution_context=ExecutionContext.interactive(),
    )

    assert (
        result["execution_context"].mode
        == ExecutionMode.INTERACTIVE
    )
    assert result["user_requested"] is True
    assert result["response"] == "Test response."
    assert len(graph.calls) == 1


def test_autonomous_execution_builds_autonomous_state():
    graph = FakeAgentGraph()
    service = NOVAExecutionService(graph)

    result = service.execute(
        user_id="user-001",
        conversation_id=None,
        user_message="A background event occurred.",
        history=[],
        execution_context=ExecutionContext.autonomous(),
    )

    assert (
        result["execution_context"].mode
        == ExecutionMode.AUTONOMOUS
    )
    assert result["user_requested"] is False
    assert len(graph.calls) == 1


def test_initial_state_preserves_core_execution_data():
    graph = FakeAgentGraph()
    service = NOVAExecutionService(graph)

    history = [
        {
            "role": "user",
            "content": "My previous message.",
        }
    ]

    state = service.build_initial_state(
        user_id="user-123",
        conversation_id=55,
        user_message="Current message",
        history=history,
        execution_context=ExecutionContext.interactive(),
    )

    assert state["user_id"] == "user-123"
    assert state["conversation_id"] == 55
    assert state["user_message"] == "Current message"
    assert state["history"] == history
    assert state["user_requested"] is True


def test_execution_requires_explicit_context():
    graph = FakeAgentGraph()
    service = NOVAExecutionService(graph)

    try:
        service.execute(
            user_id="user-001",
            conversation_id=None,
            user_message="Test",
            history=[],
            execution_context=None,
        )
    except TypeError as exc:
        assert (
            str(exc)
            == "execution_context must be an ExecutionContext instance."
        )
    else:
        raise AssertionError(
            "Execution must require an explicit ExecutionContext."
        )