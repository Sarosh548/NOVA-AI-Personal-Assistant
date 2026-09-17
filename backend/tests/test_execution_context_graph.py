from types import SimpleNamespace

from agent import graph
from services.execution_context import (
    ExecutionContext,
    ExecutionMode,
)


def _tool_state(execution_context):
    return {
        "user_id": "user-001",
        "conversation_id": None,
        "user_message": "create a task",
        "history": [],
        "understanding": {},
        "plan": {
            "requires_tool": True,
            "tool": "task",
            "action": "create",
            "data": {
                "title": "Test task",
            },
            "reason": "Create task",
        },
        "permission": {},
        "user_requested": False,
        "execution_context": execution_context,
        "confirmation": {},
        "tool_result": {},
        "memory_context": "",
        "response": "",
    }


def test_permission_node_uses_interactive_execution_context(
    monkeypatch,
):
    captured = {}

    def fake_check(**kwargs):
        captured.update(kwargs)

        return SimpleNamespace(
            allowed=True,
            requires_confirmation=False,
            reason="Allowed.",
        )

    monkeypatch.setattr(
        graph.permission_service,
        "check",
        fake_check,
    )

    state = _tool_state(
        ExecutionContext.interactive()
    )

    result = graph.permission_node(state)

    assert (
        captured["user_requested"]
        is True
    )
    assert (
        result["permission"]["allowed"]
        is True
    )


def test_permission_node_uses_autonomous_execution_context(
    monkeypatch,
):
    captured = {}

    def fake_check(**kwargs):
        captured.update(kwargs)

        return SimpleNamespace(
            allowed=False,
            requires_confirmation=False,
            reason="Autonomous execution not allowed.",
        )

    monkeypatch.setattr(
        graph.permission_service,
        "check",
        fake_check,
    )

    state = _tool_state(
        ExecutionContext.autonomous()
    )

    result = graph.permission_node(state)

    assert (
        captured["user_requested"]
        is False
    )
    assert (
        result["permission"]["allowed"]
        is False
    )


def test_permission_node_supports_legacy_user_requested_fallback(
    monkeypatch,
):
    captured = {}

    def fake_check(**kwargs):
        captured.update(kwargs)

        return SimpleNamespace(
            allowed=True,
            requires_confirmation=False,
            reason="Allowed.",
        )

    monkeypatch.setattr(
        graph.permission_service,
        "check",
        fake_check,
    )

    state = _tool_state(
        None
    )
    state.pop("execution_context")
    state["user_requested"] = True

    graph.permission_node(state)

    assert (
        captured["user_requested"]
        is True
    )


def test_missing_execution_context_defaults_to_autonomous(
    monkeypatch,
):
    captured = {}

    def fake_check(**kwargs):
        captured.update(kwargs)

        return SimpleNamespace(
            allowed=False,
            requires_confirmation=False,
            reason="Autonomous execution not allowed.",
        )

    monkeypatch.setattr(
        graph.permission_service,
        "check",
        fake_check,
    )

    state = _tool_state(
        None
    )
    state.pop("execution_context")
    state.pop("user_requested")

    graph.permission_node(state)

    assert (
        captured["user_requested"]
        is False
    )


def test_execution_context_values_are_correct():
    interactive = ExecutionContext.interactive()
    autonomous = ExecutionContext.autonomous()

    assert (
        interactive.mode
        == ExecutionMode.INTERACTIVE
    )
    assert (
        autonomous.mode
        == ExecutionMode.AUTONOMOUS
    )
    assert interactive.user_requested is True
    assert autonomous.user_requested is False