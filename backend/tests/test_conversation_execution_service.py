from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.conversation_execution_service import (
    ConversationExecutionService,
)
from services.execution_context import (
    ExecutionContext,
)


class FakeConversationService:
    def __init__(self):
        self.history = []
        self.calls = []
        self.saved_messages = []
        self.title_updates = []

    def get_or_create_conversation(
        self,
        *,
        user_id,
        conversation_id,
    ):
        self.calls.append(
            (
                "get_or_create_conversation",
                user_id,
                conversation_id,
            )
        )
        return conversation_id or 42

    def get_context_history(
        self,
        *,
        user_id,
        conversation_id,
        max_messages,
        max_characters,
    ):
        self.calls.append(
            (
                "get_context_history",
                user_id,
                conversation_id,
                max_messages,
                max_characters,
            )
        )
        return list(self.history)

    def update_conversation_title(
        self,
        *,
        conversation_id,
        user_id,
        title,
    ):
        self.title_updates.append(
            (
                conversation_id,
                user_id,
                title,
            )
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


class FakeExecutionService:
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
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "user_message": user_message,
                "history": history,
                "execution_context": execution_context,
            }
        )
        return {
            "response": "NOVA response",
            "understanding": {"intent": "conversation"},
            "plan": {"requires_tool": False},
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


class FakeLLMService:
    def __init__(self):
        self.title_calls = []
        self.memory_calls = []

    def generate_conversation_title(
        self,
        message,
    ):
        self.title_calls.append(message)
        return "Voice Conversation"

    def extract_memory(
        self,
        message,
    ):
        self.memory_calls.append(message)
        return {
            "memory_text": "User likes voice interaction.",
            "category": "preference",
            "importance": 0.7,
        }


class FakeMemoryService:
    def __init__(self):
        self.calls = []

    def add_memory(
        self,
        *,
        user_id,
        memory_text,
        category,
        importance,
        user_message,
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "memory_text": memory_text,
                "category": category,
                "importance": importance,
                "user_message": user_message,
            }
        )
        return {
            "action": "created",
            "memory_text": memory_text,
        }


def _service():
    conversation = FakeConversationService()
    execution = FakeExecutionService()
    llm = FakeLLMService()
    memory = FakeMemoryService()

    service = ConversationExecutionService(
        conversation_service=conversation,
        execution_service=execution,
        llm_service=llm,
        memory_service=memory,
        context_max_messages=12,
        context_max_characters=12000,
    )

    return service, conversation, execution, llm, memory


def test_execute_message_reuses_shared_core_and_persists_result():
    service, conversation, execution, llm, memory = _service()

    result = service.execute_message(
        user_id="user-1",
        message="  Hello NOVA  ",
    )

    assert result["response"] == "NOVA response"
    assert result["conversation_id"] == 42

    assert llm.title_calls == ["Hello NOVA"]
    assert llm.memory_calls == ["Hello NOVA"]

    assert execution.calls[0]["conversation_id"] == 42
    assert execution.calls[0]["user_message"] == "Hello NOVA"
    assert isinstance(
        execution.calls[0]["execution_context"],
        ExecutionContext,
    )
    assert execution.calls[0]["execution_context"].user_requested is True

    assert conversation.saved_messages == [
        (
            "user-1",
            42,
            "user",
            "Hello NOVA",
        ),
        (
            "user-1",
            42,
            "assistant",
            "NOVA response",
        ),
    ]

    assert memory.calls[0]["user_id"] == "user-1"
    assert memory.calls[0]["user_message"] == "Hello NOVA"


def test_execute_message_reuses_existing_conversation_and_history():
    service, conversation, execution, llm, memory = _service()

    conversation.history = [
        {
            "role": "user",
            "content": "Previous message",
        }
    ]

    result = service.execute_message(
        user_id="user-1",
        message="Follow up",
        conversation_id=99,
    )

    assert result["conversation_id"] == 99
    assert execution.calls[0]["history"] == conversation.history
    assert llm.title_calls == []


def test_execute_message_preserves_explicit_execution_context():
    service, _conversation, execution, _llm, _memory = _service()

    context = ExecutionContext.autonomous()

    service.execute_message(
        user_id="user-1",
        message="Background request",
        execution_context=context,
    )

    assert execution.calls[0]["execution_context"] is context


def test_execute_message_rejects_empty_input_without_side_effects():
    service, conversation, execution, llm, memory = _service()

    result = service.execute_message(
        user_id="user-1",
        message="   ",
    )

    assert result == {
        "error": "message cannot be empty"
    }
    assert conversation.calls == []
    assert execution.calls == []
    assert llm.title_calls == []
    assert memory.calls == []
