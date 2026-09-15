from typing import Any, TypedDict


class NOVAState(TypedDict):
    user_id: str
    conversation_id: int | None
    user_message: str

    history: list[dict[str, Any]]
    understanding: dict[str, Any]

    tool_result: dict[str, Any]
    memory_context: str

    response: str