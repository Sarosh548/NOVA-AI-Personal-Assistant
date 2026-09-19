from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent import graph
import main
from api.auth import get_current_auth_context


@pytest.fixture
def authenticated_client():
    main.app.dependency_overrides[
        get_current_auth_context
    ] = lambda: SimpleNamespace(
        user=SimpleNamespace(
            id="user-001",
        )
    )

    client = TestClient(main.app)

    try:
        yield client
    finally:
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )


def test_chat_endpoint_executes_daily_activity_report_end_to_end(
    monkeypatch,
    authenticated_client,
):
    saved_messages = []
    captured_prompt = []

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
            assert max_messages == main.CONTEXT_MAX_MESSAGES
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
            assert title == "Today's Updates"

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

    class FakeMainLLMService:
        def generate_conversation_title(
            self,
            user_message,
        ):
            assert (
                user_message
                == "Aaj kya updates hain?"
            )

            return "Today's Updates"

        def extract_memory(
            self,
            user_message,
        ):
            assert (
                user_message
                == "Aaj kya updates hain?"
            )

            return None

    class FakeGraphMemoryService:
        def find_similar_memories(
            self,
            *,
            user_id,
            new_memory,
            threshold,
            limit,
        ):
            assert user_id == "user-001"
            assert (
                new_memory
                == "Aaj kya updates hain?"
            )
            assert threshold == 0.65
            assert limit == 8

            return []

        def get_profile_memories(
            self,
            *,
            user_id,
            limit,
        ):
            assert user_id == "user-001"
            assert limit == 20

            return []

    class FakeConfirmationService:
        def parse_response(
            self,
            message,
        ):
            assert (
                message
                == "Aaj kya updates hain?"
            )

            return None

        def get_latest_pending_confirmation(
            self,
            *,
            user_id,
            conversation_id,
        ):
            assert user_id == "user-001"
            assert conversation_id == 101

            return None

    class FakeActivityReportService:
        def get_daily_report(
            self,
            *,
            user_id,
        ):
            assert user_id == "user-001"

            return {
                "user_id": user_id,
                "timezone": "Asia/Karachi",
                "total_events": 3,
                "status_counts": {
                    "success": 2,
                    "pending": 1,
                },
                "event_type_counts": {
                    "workflow_completed": 2,
                    "workflow_scheduled": 1,
                },
                "successful_count": 2,
                "pending_count": 1,
                "partial_count": 0,
                "failed_count": 0,
                "blocked_count": 0,
                "important_event_count": 2,
                "important_events": [
                    {
                        "id": 3,
                        "event_type": "workflow_completed",
                        "status": "success",
                        "title": "Workflow completed",
                        "summary": (
                            "Daily workflow completed."
                        ),
                    },
                    {
                        "id": 2,
                        "event_type": "workflow_scheduled",
                        "status": "pending",
                        "title": "Workflow scheduled",
                        "summary": (
                            "Daily workflow is scheduled."
                        ),
                    },
                ],
                "recent_events": [
                    {
                        "id": 3,
                        "event_type": "workflow_completed",
                        "status": "success",
                        "title": "Workflow completed",
                        "summary": (
                            "Daily workflow completed."
                        ),
                    },
                    {
                        "id": 2,
                        "event_type": "workflow_scheduled",
                        "status": "pending",
                        "title": "Workflow scheduled",
                        "summary": (
                            "Daily workflow is scheduled."
                        ),
                    },
                    {
                        "id": 1,
                        "event_type": "task_created",
                        "status": "success",
                        "title": "Task created",
                        "summary": (
                            "Task created successfully."
                        ),
                    },
                ],
                "report_text": (
                    "Aaj 3 activities hui hain. "
                    "2 successfully complete hui hain "
                    "aur 1 activity pending hai."
                ),
                "error": None,
            }

    class FakeGraphLLMService:
        def generate_response(
            self,
            prompt,
        ):
            captured_prompt.append(prompt)

            assert (
                "Aaj 3 activities hui hain."
                in prompt
            )

            assert (
                "2 successfully complete hui hain"
                in prompt
            )

            assert (
                "1 activity pending hai"
                in prompt
            )

            return (
                "Aaj 3 activities hui hain. "
                "2 successfully complete hui hain "
                "aur 1 activity pending hai."
            )

    monkeypatch.setattr(
        main,
        "conversation_service",
        FakeConversationService(),
    )

    monkeypatch.setattr(
        main,
        "llm_service",
        FakeMainLLMService(),
    )

    monkeypatch.setattr(
        graph,
        "memory_service",
        FakeGraphMemoryService(),
    )

    monkeypatch.setattr(
        graph,
        "confirmation_service",
        FakeConfirmationService(),
    )

    monkeypatch.setattr(
        graph,
        "activity_report_service",
        FakeActivityReportService(),
    )

    monkeypatch.setattr(
        graph,
        "llm_service",
        FakeGraphLLMService(),
    )

    client = authenticated_client

    response = client.post(
        "/chat",
        json={
            "message": "Aaj kya updates hain?",
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["conversation_id"] == 101

    assert (
        payload["response"]
        == (
            "Aaj 3 activities hui hain. "
            "2 successfully complete hui hain "
            "aur 1 activity pending hai."
        )
    )

    assert (
        payload["understanding"]["intent"]
        == "activity_report"
    )

    assert (
        payload["understanding"]["requires_tool"]
        is False
    )

    assert payload["plan"] == {}

    assert payload["permission"] == {
        "allowed": False,
        "requires_confirmation": False,
        "reason": (
            "Permission check not performed yet."
        ),
    }

    assert payload["confirmation"] == {
        "id": None,
        "status": None,
        "tool": None,
        "action": None,
        "reason": None,
    }

    assert payload["tool_result"] == {
        "success": False,
        "tool": None,
        "action": None,
        "result": None,
        "error": None,
    }

    assert payload["workflow_result"] == {
        "success": False,
        "status": None,
        "steps": [],
        "error": None,
    }

    assert len(
        captured_prompt
    ) == 1

    assert saved_messages == [
        {
            "user_id": "user-001",
            "conversation_id": 101,
            "role": "user",
            "content": "Aaj kya updates hain?",
        },
        {
            "user_id": "user-001",
            "conversation_id": 101,
            "role": "assistant",
            "content": (
                "Aaj 3 activities hui hain. "
                "2 successfully complete hui hain "
                "aur 1 activity pending hai."
            ),
        },
    ]