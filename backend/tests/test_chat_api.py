from types import SimpleNamespace

from fastapi.testclient import TestClient

import main
from api.auth import get_current_auth_context
from services.execution_context import (
    ExecutionMode,
)


def _authenticated_context(
    user_id: str,
):
    return SimpleNamespace(
        user=SimpleNamespace(
            id=user_id,
        )
    )


def test_chat_requires_authentication(
    monkeypatch,
):
    def fail_if_called(*args, **kwargs):
        raise AssertionError(
            "Protected /chat must reject before service execution."
        )

    monkeypatch.setattr(
        main,
        "conversation_service",
        SimpleNamespace(
            get_or_create_conversation=fail_if_called
        ),
    )

    main.app.dependency_overrides.pop(
        get_current_auth_context,
        None,
    )

    client = TestClient(
        main.app
    )

    response = client.post(
        "/chat",
        json={
            "message": "Hello NOVA",
        },
    )

    assert response.status_code == 401


def test_chat_uses_canonical_authenticated_identity(
    monkeypatch,
):
    saved_messages = []
    captured_execution = {}

    class FakeConversationService:
        def get_or_create_conversation(
            self,
            *,
            user_id,
            conversation_id,
        ):
            assert user_id == "user-001"
            assert conversation_id is None

            return 101

        def get_context_history(
            self,
            *,
            user_id,
            conversation_id,
            max_messages,
            max_characters,
        ):
            assert user_id == "user-001"
            assert conversation_id == 101
            assert (
                max_messages
                == main.CONTEXT_MAX_MESSAGES
            )
            assert (
                max_characters
                == main.CONTEXT_MAX_CHARACTERS
            )

            return []

        def update_conversation_title(
            self,
            *,
            conversation_id,
            user_id,
            title,
        ):
            assert conversation_id == 101
            assert user_id == "user-001"
            assert title == "Hello NOVA"

        def save_message(
            self,
            *,
            user_id,
            conversation_id,
            role,
            content,
        ):
            saved_messages.append(
                {
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "role": role,
                    "content": content,
                }
            )

    class FakeLLMService:
        def generate_conversation_title(
            self,
            user_message,
        ):
            assert user_message == "Hello NOVA"

            return "Hello NOVA"

        def extract_memory(
            self,
            user_message,
        ):
            assert user_message == "Hello NOVA"

            return None

    class FakeExecutionService:
        def execute(
            self,
            *,
            user_id,
            conversation_id,
            user_message,
            history,
            execution_context,
        ):
            captured_execution.update(
                {
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "user_message": user_message,
                    "history": history,
                    "execution_context": (
                        execution_context
                    ),
                }
            )

            return {
                "response": "Hello from NOVA.",
                "understanding": {
                    "intent": "conversation"
                },
                "plan": {},
                "permission": {
                    "allowed": True,
                    "requires_confirmation": False,
                    "reason": "Conversation.",
                },
                "confirmation": {},
                "tool_result": {
                    "success": False,
                    "tool": None,
                    "action": None,
                    "result": None,
                    "error": None,
                },
                "workflow_result": {},
            }

    monkeypatch.setattr(
        main,
        "conversation_service",
        FakeConversationService(),
    )

    monkeypatch.setattr(
        main,
        "llm_service",
        FakeLLMService(),
    )

    monkeypatch.setattr(
        main,
        "execution_service",
        FakeExecutionService(),
    )

    main.app.dependency_overrides[
        get_current_auth_context
    ] = lambda: _authenticated_context(
        "user-001"
    )

    client = TestClient(
        main.app
    )

    try:
        response = client.post(
            "/chat",
            json={
                "message": "Hello NOVA",
                "user_id": "attacker-user",
            },
        )

        assert response.status_code == 200

        payload = response.json()

        assert payload["conversation_id"] == 101
        assert (
            payload["response"]
            == "Hello from NOVA."
        )

        assert (
            captured_execution["user_id"]
            == "user-001"
        )
        assert (
            captured_execution["conversation_id"]
            == 101
        )
        assert (
            captured_execution["user_message"]
            == "Hello NOVA"
        )
        assert (
            captured_execution["history"]
            == []
        )

        execution_context = (
            captured_execution[
                "execution_context"
            ]
        )

        assert (
            execution_context.mode
            == ExecutionMode.INTERACTIVE
        )
        assert (
            execution_context.user_requested
            is True
        )

        assert saved_messages == [
            {
                "user_id": "user-001",
                "conversation_id": 101,
                "role": "user",
                "content": "Hello NOVA",
            },
            {
                "user_id": "user-001",
                "conversation_id": 101,
                "role": "assistant",
                "content": "Hello from NOVA.",
            },
        ]

    finally:
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )