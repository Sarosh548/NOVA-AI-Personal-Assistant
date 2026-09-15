from typing import TypedDict


class NOVAState(TypedDict):
    user_message: str
    memory_context: str
    response: str