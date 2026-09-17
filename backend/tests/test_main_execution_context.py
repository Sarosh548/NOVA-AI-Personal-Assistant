from services.execution_context import (
    ExecutionContext,
    ExecutionMode,
)


def test_chat_execution_context_is_interactive():
    context = ExecutionContext.interactive()

    assert context.mode == ExecutionMode.INTERACTIVE
    assert context.user_requested is True
    assert context.is_interactive is True
    assert context.is_autonomous is False


def test_autonomous_context_remains_separate_from_chat_context():
    interactive = ExecutionContext.interactive()
    autonomous = ExecutionContext.autonomous()

    assert interactive != autonomous
    assert interactive.user_requested is True
    assert autonomous.user_requested is False