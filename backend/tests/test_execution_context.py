from services.execution_context import (
    DEFAULT_AUTONOMOUS_CONTEXT,
    DEFAULT_INTERACTIVE_CONTEXT,
    ExecutionContext,
    ExecutionMode,
)


def test_interactive_context_requests_are_user_requested():
    context = ExecutionContext.interactive()

    assert context.mode == ExecutionMode.INTERACTIVE
    assert context.user_requested is True
    assert context.is_interactive is True
    assert context.is_autonomous is False


def test_autonomous_context_requests_are_not_user_requested():
    context = ExecutionContext.autonomous()

    assert context.mode == ExecutionMode.AUTONOMOUS
    assert context.user_requested is False
    assert context.is_interactive is False
    assert context.is_autonomous is True


def test_default_contexts_are_correct():
    assert DEFAULT_INTERACTIVE_CONTEXT.mode == ExecutionMode.INTERACTIVE
    assert DEFAULT_INTERACTIVE_CONTEXT.user_requested is True

    assert DEFAULT_AUTONOMOUS_CONTEXT.mode == ExecutionMode.AUTONOMOUS
    assert DEFAULT_AUTONOMOUS_CONTEXT.user_requested is False


def test_context_is_immutable():
    context = ExecutionContext.interactive()

    try:
        context.mode = ExecutionMode.AUTONOMOUS
    except Exception:
        pass
    else:
        raise AssertionError("ExecutionContext must be immutable")


def test_context_instances_are_equal_by_value():
    assert ExecutionContext.interactive() == ExecutionContext(
        mode=ExecutionMode.INTERACTIVE
    )