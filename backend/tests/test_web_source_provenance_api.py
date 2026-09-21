from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
from api.auth import get_current_auth_context


class FakeConversationService:
    def __init__(self):
        self.saved_messages = []

    def get_or_create_conversation(
        self,
        *,
        user_id,
        conversation_id,
    ):
        return conversation_id or 101

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
                "content": "Previous message",
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
        self.saved_messages.append(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
            }
        )


class FakeLLMService:
    def extract_memory(self, user_message):
        return None


def _authenticated_context():
    return SimpleNamespace(
        user=SimpleNamespace(
            id="user-001",
        )
    )


@pytest.fixture
def authenticated_client():
    main.app.dependency_overrides[
        get_current_auth_context
    ] = _authenticated_context

    client = TestClient(
        main.app
    )

    try:
        yield client

    finally:
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )


def test_execute_chat_preserves_web_sources(monkeypatch):
    conversation_service = FakeConversationService()

    monkeypatch.setattr(
        main,
        "conversation_service",
        conversation_service,
    )

    monkeypatch.setattr(
        main,
        "llm_service",
        FakeLLMService(),
    )

    monkeypatch.setattr(
        main,
        "execution_service",
        SimpleNamespace(
            execute=lambda **kwargs: {
                "response": (
                    "The latest result is supported by "
                    "[Web Source 1]."
                ),
                "understanding": {
                    "intent": "web",
                },
                "plan": {
                    "requires_tool": True,
                    "tool": "web",
                    "action": "search",
                },
                "permission": {},
                "confirmation": {},
                "tool_result": {
                    "success": True,
                    "tool": "web",
                    "action": "search",
                    "result": {
                        "results": [
                            {
                                "title": "FastAPI Release",
                                "url": "https://example.com/fastapi",
                            }
                        ]
                    },
                    "error": None,
                },
                "workflow_result": {},
                "knowledge_sources": [],
                "web_sources": [
                    {
                        "label": "Web Source 1",
                        "title": "FastAPI Release",
                        "url": "https://example.com/fastapi",
                        "published_date": "2026-09-21",
                        "score": 0.98,
                    }
                ],
            }
        ),
    )

    response = main._execute_chat(
        request=main.ChatRequest(
            message="What's the latest FastAPI release?",
            conversation_id=101,
        ),
        current_user_id="user-001",
    )

    assert response["web_sources"] == [
        {
            "label": "Web Source 1",
            "title": "FastAPI Release",
            "url": "https://example.com/fastapi",
            "published_date": "2026-09-21",
            "score": 0.98,
        }
    ]


def test_chat_response_and_idempotency_preserve_web_sources(
    monkeypatch,
    authenticated_client,
):
    payload = {
        "response": (
            "The latest result is supported by "
            "[Web Source 1]."
        ),
        "conversation_id": 101,
        "understanding": {
            "intent": "web",
        },
        "plan": {},
        "permission": {},
        "confirmation": {},
        "tool_result": {
            "success": True,
        },
        "workflow_result": {},
        "memory_action": None,
        "knowledge_sources": [],
        "web_sources": [
            {
                "label": "Web Source 1",
                "title": "FastAPI Release",
                "url": "https://example.com/fastapi",
            }
        ],
    }

    monkeypatch.setattr(
        main,
        "_execute_chat",
        lambda **kwargs: dict(payload),
    )

    class FakeIdempotencyService:
        def __init__(self):
            self.completed = None

        @staticmethod
        def build_request_hash(data):
            return "request-hash"

        def claim_or_replay(
            self,
            *,
            user_id,
            endpoint,
            idempotency_key,
            request_hash,
        ):
            return {
                "status": "new",
                "record_id": 7,
                "claim_token": "claim-token",
            }

        def complete(
            self,
            *,
            record_id,
            claim_token,
            response_status,
            response_body,
        ):
            self.completed = {
                "record_id": record_id,
                "claim_token": claim_token,
                "response_status": response_status,
                "response_body": response_body,
            }

        def fail(
            self,
            **kwargs,
        ):
            raise AssertionError(
                "fail() should not be called"
            )

    idempotency_service = FakeIdempotencyService()

    monkeypatch.setattr(
        main,
        "idempotency_service",
        idempotency_service,
    )

    client = authenticated_client

    response = client.post(
        "/chat",
        headers={
            "Idempotency-Key": "web-source-test-1",
        },
        json={
            "message": "What's the latest FastAPI release?",
        },
    )

    assert response.status_code == 200
    assert response.json()["web_sources"] == [
        {
            "label": "Web Source 1",
            "title": "FastAPI Release",
            "url": "https://example.com/fastapi",
        }
    ]

    assert idempotency_service.completed is not None
    assert (
        idempotency_service.completed["response_body"][
            "web_sources"
        ]
        == response.json()["web_sources"]
    )
