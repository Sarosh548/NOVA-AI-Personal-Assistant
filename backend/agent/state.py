from typing import Any, NotRequired, TypedDict

from services.execution_context import ExecutionContext


class NOVAState(TypedDict):
    user_id: str
    conversation_id: int | None
    user_message: str
    history: list[dict[str, Any]]
    understanding: dict[str, Any]
    plan: dict[str, Any]
    permission: dict[str, Any]
    user_requested: bool
    execution_context: ExecutionContext
    confirmation: dict[str, Any]
    tool_result: dict[str, Any]
    workflow_result: dict[str, Any]
    memory_context: str
    response: str
    activity_report: NotRequired[dict[str, Any]]