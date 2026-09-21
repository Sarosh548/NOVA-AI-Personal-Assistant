from types import SimpleNamespace

from fastapi.testclient import TestClient

import main
from api.auth import get_current_auth_context


def _authenticated_context(user_id: str):
    return SimpleNamespace(
        user=SimpleNamespace(
            id=user_id,
        )
    )


def test_chat_returns_knowledge_sources():
    class FakeConversationService:
        def get_or_create_conversation(
            self,
            *,
            user_id,
            conversation_id,
        ):
            return 202

        def get_context_history(
            self,
            *,
            user_id,
            conversation_id,
            max_messages,
            max_characters,
        ):
            return [
                {
                    "role": "user",
                    "content": "Tell me about my Python guide.",
                }
            ]

        def save_message(
            self,
            *,
            user_id,
            conversation_id,
            role,
            content,
        ):
            pass

    class FakeLLMService:
        def extract_memory(self, user_message):
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
            return {
                "response": "Python is useful for AI development. [Source 1]",
                "understanding": {
                    "intent": "question"
                },
                "plan": {},
                "permission": {},
                "confirmation": {},
                "tool_result": {
                    "success": False,
                    "tool": None,
                    "action": None,
                    "result": None,
                    "error": None,
                },
                "workflow_result": {},
                "knowledge_sources": [
                    {
                        "document_id": 7,
                        "title": "Python Guide",
                        "source": "manual",
                        "chunk_index": 0,
                        "similarity": 0.91,
                    }
                ],
            }

    original_conversation_service = main.conversation_service
    original_llm_service = main.llm_service
    original_execution_service = main.execution_service

    main.conversation_service = FakeConversationService()
    main.llm_service = FakeLLMService()
    main.execution_service = FakeExecutionService()

    main.app.dependency_overrides[
        get_current_auth_context
    ] = lambda: _authenticated_context(
        "user-001"
    )

    client = TestClient(main.app)

    try:
        response = client.post(
            "/chat",
            json={
                "message": "Tell me about my Python guide."
            },
        )

        assert response.status_code == 200

        payload = response.json()

        assert payload["knowledge_sources"] == [
            {
                "document_id": 7,
                "title": "Python Guide",
                "source": "manual",
                "chunk_index": 0,
                "similarity": 0.91,
            }
        ]

    finally:
        main.conversation_service = original_conversation_service
        main.llm_service = original_llm_service
        main.execution_service = original_execution_service
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )
