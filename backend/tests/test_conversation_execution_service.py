from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.conversation_execution_service import (
    ConversationExecutionService,
    _append_requested_web_sources,
    _clarify_chat_only_email_draft,
    _format_persisted_task_list_response,
    _format_persisted_reminder_list_response,
    _format_failed_read_action_response,
    _simple_arithmetic_response,
)
from services.execution_context import (
    ExecutionContext,
)


def test_persisted_task_list_response_uses_real_task_rows():
    response = _format_persisted_task_list_response(
        {
            "success": True,
            "tool": "task",
            "action": "list",
            "error": None,
            "result": {
                "count": 1,
                "tasks": [
                    {
                        "id": 123,
                        "title": "Nova Live Test Task 1021",
                        "status": "pending",
                        "priority": "medium",
                        "due_at": None,
                    }
                ],
            },
        }
    )

    assert response is not None
    assert "Nova Live Test Task 1021" in response
    assert "status: pending" in response
    assert "priority: medium" in response
    assert "system access" not in response.lower()


def test_persisted_task_list_response_reports_empty_saved_list():
    response = _format_persisted_task_list_response(
        {
            "success": True,
            "tool": "task",
            "action": "list",
            "error": None,
            "result": {"count": 0, "tasks": []},
        }
    )

    assert response == "Aapki saved task list mein abhi koi task nahi mila."


def test_persisted_task_list_verifies_title_for_devanagari_request():
    response = _format_persisted_task_list_response(
        {
            "success": True,
            "tool": "task",
            "action": "list",
            "error": None,
            "result": {
                "count": 1,
                "tasks": [
                    {
                        "id": 123,
                        "title": "Nova Live Test task. 1021 ko due date mat lagana",
                        "status": "pending",
                        "priority": "medium",
                        "due_at": None,
                    }
                ],
            },
        },
        user_message="मेरी टास्क लिस्ट देखो और वेरीफाई करो कि Nova Lite टास्क लिस्ट में है या नहीं।",
    )

    assert response is not None
    assert "Verification: exact 'nova lite' task saved list mein nahi mila." in response
    assert "Saved record ka actual title: 'Nova Live Test task. 1021 ko due date mat lagana'." in response


def test_persisted_task_list_verifies_saved_phrase_and_reports_asr_suffix_mismatch():
    response = _format_persisted_task_list_response(
        {
            "success": True,
            "tool": "task",
            "action": "list",
            "error": None,
            "result": {
                "count": 1,
                "tasks": [
                    {
                        "id": 456,
                        "title": "Nova Retest Task 1021B",
                        "status": "pending",
                        "priority": "medium",
                        "due_at": None,
                    }
                ],
            },
        },
        user_message="Show my task and verify that Nova Retest Task 1021 is saved.",
    )

    assert response is not None
    assert "Nova Retest Task 1021B" in response
    assert "verification: exact title 'nova retest task 1021' nahi mila" in response.lower()
    assert "closest saved title 'nova retest task 1021b'" in response.lower()
    assert "voice transcript mein title ka chhota hissa miss hua ho sakta hai." in response.lower()


def test_persisted_task_list_verifies_exact_saved_title():
    response = _format_persisted_task_list_response(
        {
            "success": True,
            "tool": "task",
            "action": "list",
            "error": None,
            "result": {
                "count": 1,
                "tasks": [
                    {
                        "id": 457,
                        "title": "Nova Retest Task 1021B",
                        "status": "pending",
                        "priority": "medium",
                        "due_at": None,
                    }
                ],
            },
        },
        user_message="Verify that Nova Retest Task 1021B is saved.",
    )

    assert response is not None
    assert "verification: exact 'nova retest task 1021b' saved task list mein mila." in response.lower()


def test_persisted_reminder_list_response_uses_real_reminder_rows():
    response = _format_persisted_reminder_list_response(
        {
            "success": True,
            "tool": "reminder",
            "action": "list",
            "error": None,
            "result": {
                "count": 1,
                "reminders": [
                    {
                        "id": 17,
                        "title": "NOVA QA reminder",
                        "reminder_time": "2026-10-27T10:00:00+05:00",
                        "status": "pending",
                    }
                ],
            },
        },
        user_message="List my reminders. Read-only; do not create or modify anything.",
    )

    assert response is not None
    assert "NOVA QA reminder" in response
    assert "status: pending" in response
    assert "scheduled: 2026-10-27T10:00:00+05:00" in response
    assert "direct access" not in response.lower()


def test_persisted_reminder_list_response_reports_empty_saved_list():
    response = _format_persisted_reminder_list_response(
        {
            "success": True,
            "tool": "reminder",
            "action": "list",
            "error": None,
            "result": {"count": 0, "reminders": []},
        }
    )

    assert response == "Aapki saved reminder list mein abhi koi pending reminder nahi mila."


def test_persisted_reminder_list_response_does_not_hide_tool_errors():
    response = _format_persisted_reminder_list_response(
        {
            "success": False,
            "tool": "reminder",
            "action": "list",
            "error": "Database unavailable.",
            "result": None,
        }
    )

    assert response is None


def test_failed_gmail_list_exposes_missing_read_permission_safely():
    response = _format_failed_read_action_response(
        {
            "success": False,
            "tool": "email",
            "action": "list",
            "result": None,
            "error": (
                "Gmail inbox access has not been granted. Reconnect Google/Gmail from "
                "Control Center → Notifications and approve the requested read-only email permission."
            ),
        }
    )

    assert response is not None
    assert "read-only Gmail permission" in response
    assert "No email was sent" in response


def test_failed_calendar_list_is_not_reported_as_an_empty_calendar():
    response = _format_failed_read_action_response(
        {
            "success": False,
            "tool": "calendar",
            "action": "list",
            "result": None,
            "error": "Google Calendar is not connected.",
        }
    )

    assert response is not None
    assert "not connected or authorized" in response
    assert "No Calendar changes were made" in response
    assert "no events" not in response.lower()


def test_read_error_formatter_does_not_override_successful_results():
    response = _format_failed_read_action_response(
        {
            "success": True,
            "tool": "calendar",
            "action": "list",
            "result": {"events": []},
            "error": None,
        }
    )

    assert response is None


def test_latest_source_request_does_not_repeat_stale_answer_when_no_fresh_sources():
    response = _append_requested_web_sources(
        "Artemis II launched in June 2026.",
        "Search the web for the latest NASA Artemis II update and give me two source links.",
        {
            "success": True,
            "tool": "web",
            "action": "search",
            "result": {"results": []},
            "error": None,
        },
    )

    assert "couldn't verify a fresh, dated source" in response.lower()
    assert "won't present older articles as the latest update" in response.lower()
    assert "launched in june" not in response.lower()


def test_requested_web_source_links_include_only_real_retrieved_urls():
    response = _append_requested_web_sources(
        "No independent winner can be verified from these sources.",
        "Compare assistants and give me source links.",
        {
            "success": True,
            "tool": "web",
            "action": "search",
            "result": {
                "results": [
                    {
                        "title": "Official Voice Documentation",
                        "url": "https://example.com/voice",
                        "published_date": "2026-10-20",
                    },
                    {"title": "Invalid source", "url": "javascript:alert(1)"},
                ]
            },
        },
    )

    assert "Official Voice Documentation" in response
    assert "https://example.com/voice" in response
    assert "javascript:" not in response
    assert "Sources (open links):" in response


def test_requested_web_source_links_format_pakistan_time_without_utc_date_rollover():
    response = _append_requested_web_sources(
        "Here is one verified story.",
        "Please include source links.",
        {
            "success": True,
            "tool": "web",
            "action": "search",
            "result": {
                "results": [
                    {
                        "title": "An AI news story",
                        "url": "https://example.com/ai-news",
                        "published_date": "2026-10-28T01:00:00+05:00",
                    }
                ]
            },
        },
    )

    assert "(published: 28 Oct 2026, 01:00 AM PKT)" in response


def test_requested_ai_news_reports_when_fewer_fresh_sources_than_requested():
    response = _append_requested_web_sources(
        "- One dated AI story.",
        (
            "Search the web for the latest AI news from today. Give exactly 3 distinct "
            "news items, each with publication date in Pakistan time and a direct source link."
        ),
        {
            "success": True,
            "tool": "web",
            "action": "search",
            "result": {
                "results": [
                    {
                        "title": "One dated AI story",
                        "url": "https://example.com/ai-today",
                        "published_date": "2026-10-28T01:00:00+05:00",
                    }
                ]
            },
        },
    )

    assert "I could verify only 1 qualifying AI-news item for today, out of 3 requested." in response
    assert "I won't pad the list with older or unrelated stories." in response
    assert "https://example.com/ai-today" in response


def test_requested_ai_news_reports_zero_qualifying_sources():
    response = _append_requested_web_sources(
        "The older article is not a qualifying result.",
        (
            "Search for the latest AI news today. Give exactly 3 distinct news items "
            "with source links. Exclude stories from before today."
        ),
        {
            "success": True,
            "tool": "web",
            "action": "search",
            "result": {"results": []},
        },
    )

    assert "I could verify only 0 qualifying AI-news items for today, out of 3 requested." in response
    assert "I won't pad the list with older or unrelated stories." in response


def test_web_sources_are_not_appended_when_not_requested():
    response = _append_requested_web_sources(
        "Here is a general answer.",
        "Tell me about voice assistants.",
        {
            "success": True,
            "tool": "web",
            "action": "search",
            "result": {"results": [{"title": "Page", "url": "https://example.com"}]},
        },
    )

    assert response == "Here is a general answer."


def test_unsent_email_draft_is_explicitly_chat_only():
    response = _clarify_chat_only_email_draft(
        'Aapka email draft ho gaya hai. Subject "Nova test" hai.',
        "एक ईमेल ड्राफ्ट करो सब्जेक्ट नोवा टेस्ट हो और बॉडी में लिखो दिस इज अ टेस्ट ईमेल अभी सेंड मत करना।",
        {
            "success": False,
            "tool": None,
            "action": None,
            "error": None,
        },
    )

    assert "draft" in response.lower()
    assert "Gmail ke Drafts mein save nahi hua" in response
    assert "send bhi nahi hua" in response


def test_successful_real_draft_tool_would_not_receive_chat_only_warning():
    response = _clarify_chat_only_email_draft(
        "The email draft was saved.",
        "Draft an email and do not send it.",
        {"success": True, "tool": "email", "action": "draft"},
    )

    assert response == "The email draft was saved."


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
        self.voice_calls = []
        self.companion_calls = []
        self.raise_memory_error = False
        self.raise_title_error = False

    def generate_companion_response(
        self,
        *,
        message,
        history,
        memory_context,
    ):
        self.companion_calls.append(
            {
                "message": message,
                "history": history,
                "memory_context": memory_context,
            }
        )
        return "NOVA companion response"

    def generate_voice_response_stream(
        self,
        *,
        message,
        history,
        memory_context,
    ):
        self.voice_calls.append(
            {
                "message": message,
                "history": history,
                "memory_context": memory_context,
            }
        )
        yield "NOVA voice"
        yield " response"

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
        if self.raise_memory_error:
            raise RuntimeError("memory provider unavailable")
        return {
            "memory_text": "User likes voice interaction.",
            "category": "preference",
            "importance": 0.7,
        }


class FakeMemoryService:
    def __init__(self):
        self.calls = []
        self.similar_memories = []
        self.profile_memories = []

    def find_similar_memories(
        self,
        *,
        user_id,
        new_memory,
        threshold=0.65,
        limit=8,
    ):
        return list(self.similar_memories)[:limit]

    def get_profile_memories(self, *, user_id, limit=20):
        return list(self.profile_memories)[:limit]

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


def test_prepare_conversation_uses_shared_conversation_boundary():
    service, conversation, _execution, _llm, _memory = _service()

    result = service.prepare_conversation(
        user_id="user-1",
        conversation_id=None,
    )

    assert result == 42
    assert conversation.calls == [
        (
            "get_or_create_conversation",
            "user-1",
            None,
        )
    ]


def test_execute_message_reuses_shared_core_and_persists_result():
    service, conversation, execution, llm, memory = _service()

    result = service.execute_message(
        user_id="user-1",
        message="  Create a task to practice LangGraph  ",
    )

    assert result["response"] == "NOVA response"
    assert result["conversation_id"] == 42

    assert llm.title_calls == []
    assert llm.memory_calls == []

    assert execution.calls[0]["conversation_id"] == 42
    assert (
        execution.calls[0]["user_message"]
        == "Create a task to practice LangGraph"
    )
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
            "Create a task to practice LangGraph",
        ),
        (
            "user-1",
            42,
            "assistant",
            "NOVA response",
        ),
    ]

    assert memory.calls == []


def test_execute_message_routes_planning_follow_up_to_full_graph():
    service, conversation, execution, llm, memory = _service()
    conversation.history = [
        {
            "role": "user",
            "content": (
                "Help me plan tomorrow. I have to work on NOVA, "
                "study AI, apply for jobs, and also get some rest."
            ),
        }
    ]

    result = service.execute_message(
        user_id="user-1",
        message="I only have three hours for focused work.",
    )

    assert result["response"] == "NOVA response"
    assert len(execution.calls) == 1
    assert llm.companion_calls == []


def test_execute_message_routes_focused_work_duration_without_history_to_full_graph():
    service, conversation, execution, llm, memory = _service()

    result = service.execute_message(
        user_id="user-1",
        message="I only have three hours for focused work.",
    )

    assert result["response"] == "NOVA response"
    assert len(execution.calls) == 1
    assert llm.companion_calls == []


def test_execute_message_routes_first_follow_up_after_focused_work_to_full_graph():
    service, conversation, execution, llm, memory = _service()
    conversation.history = [
        {
            "role": "user",
            "content": "I only have three hours for focused work.",
        },
    ]

    result = service.execute_message(
        user_id="user-1",
        message="What should I do first?",
    )

    assert result["response"] == "NOVA response"
    assert len(execution.calls) == 1
    assert llm.companion_calls == []


def test_execute_message_routes_activity_updates_to_full_graph():
    service, conversation, execution, llm, memory = _service()

    result = service.execute_message(
        user_id="user-1",
        message="Aaj kya updates hain?",
    )

    assert result["response"] == "NOVA response"
    assert len(execution.calls) == 1
    assert llm.companion_calls == []


def test_execute_message_routes_private_knowledge_reference_to_full_graph():
    service, conversation, execution, llm, memory = _service()

    result = service.execute_message(
        user_id="user-1",
        message="Tell me about my Python guide.",
    )

    assert result["response"] == "NOVA response"
    assert len(execution.calls) == 1
    assert llm.companion_calls == []


def test_execute_message_keeps_chained_planning_follow_up_on_full_graph():
    service, conversation, execution, llm, memory = _service()
    conversation.history = [
        {
            "role": "user",
            "content": "What should I do first?",
        },
        {
            "role": "assistant",
            "content": (
                "Start with the NOVA work, then move to AI study "
                "and job applications."
            ),
        },
        {
            "role": "user",
            "content": "What can wait until tomorrow?",
        },
        {
            "role": "assistant",
            "content": (
                "AI study and job applications can wait if needed."
            ),
        },
    ]

    result = service.execute_message(
        user_id="user-1",
        message="I only have three hours for focused work.",
    )

    assert result["response"] == "NOVA response"
    assert len(execution.calls) == 1
    assert llm.companion_calls == []


def test_execute_message_uses_fast_companion_path_for_ordinary_chat():
    service, conversation, execution, llm, memory = _service()

    result = service.execute_message(
        user_id="user-1",
        message="  Hey NOVA, how are you?  ",
    )

    assert result["response"] == "NOVA companion response"
    assert result["conversation_id"] == 42
    assert execution.calls == []
    assert llm.companion_calls == [
        {
            "message": "Hey NOVA, how are you?",
            "history": [],
            "memory_context": "",
        }
    ]
    assert llm.memory_calls == []
    assert result["memory_action"] is None
    assert conversation.saved_messages == [
        (
            "user-1",
            42,
            "user",
            "Hey NOVA, how are you?",
        ),
        (
            "user-1",
            42,
            "assistant",
            "NOVA companion response",
        ),
    ]
    assert conversation.title_updates == [
        (
            42,
            "user-1",
            "Hey NOVA, how are you",
        )
    ]


def test_execute_message_uses_full_graph_for_memory_write_request():
    service, conversation, execution, llm, memory = _service()

    result = service.execute_message(
        user_id="user-1",
        message="Remember that my main career goal is AI Engineer.",
    )

    assert result["response"] == "NOVA response"
    assert len(execution.calls) == 1
    assert llm.companion_calls == []
    assert llm.memory_calls == [
        "Remember that my main career goal is AI Engineer."
    ]
    assert result["memory_action"] == {
        "action": "created",
        "memory_text": "User likes voice interaction.",
    }


def test_execute_message_uses_full_graph_for_web_request():
    service, conversation, execution, llm, memory = _service()

    result = service.execute_message(
        user_id="user-1",
        message="Search the web for the latest AI news.",
    )

    assert result["response"] == "NOVA response"
    assert len(execution.calls) == 1
    assert llm.companion_calls == []


def test_execute_message_uses_safe_fallback_for_empty_graph_response():
    service, conversation, execution, _llm, _memory = _service()
    graph_execute = execution.execute

    def execute_with_empty_response(**kwargs):
        result = graph_execute(**kwargs)
        result["response"] = ""
        return result

    execution.execute = execute_with_empty_response
    message = "Search the web for the latest AI news."

    result = service.execute_message(
        user_id="user-1",
        message=message,
    )

    expected = (
        "I couldn't produce a complete answer just now. "
        "No external action was taken. Please try again in a moment."
    )
    assert result["response"] == expected
    assert conversation.saved_messages[-2:] == [
        ("user-1", 42, "user", message),
        ("user-1", 42, "assistant", expected),
    ]


def test_email_draft_follow_ups_bypass_fast_path():
    history = [
        {
            "role": "user",
            "content": (
                'Mujhe ek email send karni hai. Email ka exact message '
                'yeh hai: "NOVA multi-turn context test successful." '
                "Pehle mujh se recipient email address poochho."
            ),
        },
        {
            "role": "assistant",
            "content": (
                "Who should receive the email, and what subject would you like?"
            ),
        },
    ]

    for follow_up in (
        "saroshqaiser4@gmail.com",
        "koi subject na rko",
        "yes",
        "send kr di",
    ):
        assert not ConversationExecutionService._is_fast_conversation(
            follow_up,
            history=history,
        )

    # Unrelated requests should still use the ordinary conversational path.
    assert ConversationExecutionService._is_fast_conversation(
        "Tell me a joke.",
        history=history,
    )


def test_task_creation_confirmation_bypasses_fast_path():
    history = [
        {
            "role": "user",
            "content": (
                "Haan isko create kar do. Title hai Nova Live Title Check 2338, okay?"
            ),
        },
        {
            "role": "assistant",
            "content": (
                "I will add a task titled Nova Live Title Check 2338 with default priority. "
                "Let me know if that is exactly what you want, and I will create it right now."
            ),
        },
    ]

    assert not ConversationExecutionService._is_fast_conversation(
        "Okay, okay. Yes, this is what I want.",
        history=history,
    )
    assert ConversationExecutionService._is_fast_conversation(
        "Tell me a joke.",
        history=history,
    )

    hindi_task_request = (
        "\u0939\u093e\u0902, \u0907\u0938\u0915\u094b "
        "\u0915\u094d\u0930\u093f\u090f\u091f \u0915\u0930 \u0926\u094b\u0964 "
        "\u091f\u093e\u0907\u091f\u0932 \u0939\u0948 Nova Live Title Check 2338"
    )
    assert not ConversationExecutionService._is_fast_conversation(
        hindi_task_request,
        history=[],
    )


def test_plain_text_subject_after_recipient_bypasses_fast_path():
    history = [
        {
            "role": "user",
            "content": (
                'Mujhe ek email send karni hai. Email ka exact message '
                'yeh hai: "NOVA multi-turn context test successful." '
                "Pehle mujh se recipient email address poochho."
            ),
        },
        {
            "role": "assistant",
            "content": "Sure! Could you let me know the recipient's email address?",
        },
        {
            "role": "user",
            "content": "saroshqaiser4@gmail.com",
        },
        {
            "role": "assistant",
            "content": (
                "Sure thing! What would you like me to do with that email address? "
                "Need help composing a message, adding it to a contact list, or "
                "something else? Just let me know!"
            ),
        },
    ]

    assert not ConversationExecutionService._is_fast_conversation(
        "NOVA multi-turn context test",
        history=history,
    )
    assert ConversationExecutionService._is_fast_conversation(
        "Tell me a joke.",
        history=history,
    )


def test_execute_message_routes_email_draft_recipient_to_full_graph():
    service, conversation, execution, llm, _memory = _service()
    conversation.history = [
        {
            "role": "user",
            "content": (
                'Mujhe ek email send karni hai. Email ka exact message '
                'yeh hai: "NOVA multi-turn context test successful." '
                "Pehle mujh se recipient email address poochho."
            ),
        },
        {
            "role": "assistant",
            "content": (
                "Who should receive the email, and what subject would you like?"
            ),
        },
    ]

    result = service.execute_message(
        user_id="user-1",
        message="saroshqaiser4@gmail.com",
    )

    assert result["response"] == "NOVA response"
    assert len(execution.calls) == 1
    assert execution.calls[0]["user_message"] == "saroshqaiser4@gmail.com"
    assert execution.calls[0]["history"] == conversation.history
    assert llm.companion_calls == []


def test_execute_message_bypasses_fast_path_while_confirmation_is_pending():
    service, conversation, execution, llm, memory = _service()
    confirmation_lookups = []

    class FakeConfirmationService:
        def get_latest_pending_confirmation(self, *, user_id, conversation_id):
            confirmation_lookups.append((user_id, conversation_id))
            return {
                "id": 88,
                "status": "pending",
                "tool": "email",
                "action": "send",
            }

    service.confirmation_service = FakeConfirmationService()

    result = service.execute_message(
        user_id="user-1",
        message="saroshqaiser4@gmail.com",
    )

    assert result["response"] == "NOVA response"
    assert len(execution.calls) == 1
    assert llm.companion_calls == []
    assert confirmation_lookups == [("user-1", 42)]


def test_execute_message_uses_local_title_without_extra_llm_call():
    service, conversation, execution, llm, memory = _service()

    result = service.execute_message(
        user_id="user-1",
        message="Create a task for NOVA",
    )

    assert result["response"] == "NOVA response"
    assert conversation.saved_messages[-2:] == [
        ("user-1", 42, "user", "Create a task for NOVA"),
        ("user-1", 42, "assistant", "NOVA response"),
    ]
    assert conversation.title_updates == [
        (42, "user-1", "Create a task for NOVA")
    ]
    assert llm.title_calls == []


def test_execute_message_preserves_response_when_memory_extraction_fails():
    service, conversation, execution, llm, memory = _service()
    llm.raise_memory_error = True

    result = service.execute_message(
        user_id="user-1",
        message="Remember that my main career goal is AI Engineer.",
    )

    assert result["response"] == "NOVA response"
    assert result["memory_action"] is None
    assert conversation.saved_messages == [
        (
            "user-1",
            42,
            "user",
            "Remember that my main career goal is AI Engineer.",
        ),
        (
            "user-1",
            42,
            "assistant",
            "NOVA response",
        ),
    ]
    assert memory.calls == []


def test_execute_message_skips_persistence_when_execution_is_superseded():
    service, conversation, execution, llm, memory = _service()

    result = service.execute_message(
        user_id="user-1",
        message="Interrupted request",
        is_execution_current=lambda: False,
    )

    assert result == {
        "cancelled": True,
        "conversation_id": 42,
    }

    assert execution.calls == []
    assert conversation.saved_messages == []
    assert conversation.title_updates == []
    assert llm.title_calls == []
    assert memory.calls == []


def test_execute_message_skips_persistence_when_execution_becomes_stale():
    service, conversation, execution, llm, memory = _service()

    current_checks = iter([True, False])

    result = service.execute_message(
        user_id="user-1",
        message="Create a task for NOVA",
        is_execution_current=lambda: next(current_checks),
    )

    assert result == {
        "cancelled": True,
        "conversation_id": 42,
    }

    assert len(execution.calls) == 1
    assert conversation.saved_messages == []
    assert conversation.title_updates == []
    assert llm.title_calls == []
    assert memory.calls == []


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
        message="Create a task",
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


def test_execute_message_skips_title_llm_for_realtime_voice():
    service, conversation, execution, llm, memory = _service()

    context = ExecutionContext.interactive(voice=True)

    result = service.execute_message(
        user_id="user-1",
        message="Hello NOVA from voice",
        execution_context=context,
    )

    assert result["response"] == "NOVA response"
    assert llm.title_calls == []
    assert execution.calls[0]["execution_context"].is_voice is True


def test_fast_voice_conversation_uses_compact_streaming_path():
    service, conversation, execution, llm, memory = _service()

    result = service.execute_voice_message(
        user_id="user-1",
        message="Hey NOVA, how are you?",
    )

    assert result["response"] == "NOVA voice response"
    assert llm.voice_calls[0]["message"] == "Hey NOVA, how are you?"
    assert execution.calls == []
    assert conversation.saved_messages[-2:] == [
        (
            "user-1",
            42,
            "user",
            "Hey NOVA, how are you?",
        ),
        (
            "user-1",
            42,
            "assistant",
            "NOVA voice response",
        ),
    ]


def test_voice_action_request_stays_on_full_agent_graph():
    service, conversation, execution, llm, memory = _service()

    result = service.execute_voice_message(
        user_id="user-1",
        message="Remind me tomorrow to call HR",
    )

    assert result["response"] == "NOVA response"
    assert llm.voice_calls == []
    assert execution.calls[0]["execution_context"].is_voice is True


def test_voice_fast_path_keeps_roman_urdu_actions_on_safe_graph():
    service, conversation, execution, llm, memory = _service()

    result = service.execute_voice_message(
        user_id="user-1",
        message="kal mujhe HR ko call karne ki yaad dila do",
    )

    assert result["response"] == "NOVA response"
    assert llm.voice_calls == []
    assert execution.calls[0]["execution_context"].is_voice is True


def test_voice_fast_path_keeps_fresh_information_on_safe_graph():
    service, conversation, execution, llm, memory = _service()

    result = service.execute_voice_message(
        user_id="user-1",
        message="aaj ki AI news batao",
    )

    assert result["response"] == "NOVA response"
    assert llm.voice_calls == []
    assert execution.calls[0]["execution_context"].is_voice is True


@pytest.mark.parametrize(
    "message",
    [
        "Tell me like today in cricket which man is live right now?",
        "Who is playing in cricket right now?",
        "Are there any cricket matches happening today?",
    ],
)
def test_voice_live_sports_questions_bypass_companion_fast_path(message):
    service, _conversation, execution, llm, _memory = _service()

    assert ConversationExecutionService._is_fast_conversation(message) is False

    result = service.execute_voice_message(
        user_id="user-1",
        message=message,
    )

    assert result["response"] == "NOVA response"
    assert len(execution.calls) == 1
    assert execution.calls[0]["user_message"] == message
    assert execution.calls[0]["execution_context"].is_voice is True
    assert llm.voice_calls == []
    assert llm.companion_calls == []


def test_execute_message_returns_safe_fallback_when_fast_provider_is_unavailable(
    monkeypatch,
):
    service, conversation, execution, llm, _memory = _service()

    def fail_generate_companion_response(**kwargs):
        raise RuntimeError("provider rate limit")

    monkeypatch.setattr(
        llm,
        "generate_companion_response",
        fail_generate_companion_response,
    )
    monkeypatch.setattr(
        "services.conversation_execution_service.is_llm_provider_error",
        lambda exc: True,
    )

    result = service.execute_message(
        user_id="user-1",
        message="Tell me something useful.",
    )

    assert result["response"] == (
        "I'm having a temporary connection issue with my AI service right now. "
        "I haven't taken any action. Please try again in a moment."
    )
    assert execution.calls == []
    assert conversation.saved_messages[-1][3] == result["response"]


class FakeKnowledgeService:
    def __init__(self):
        self.create_calls = []
        self.search_calls = []
        self.empty_queries = set()

    def create_document(
        self,
        *,
        user_id,
        title,
        content,
        source,
    ):
        self.create_calls.append(
            {
                "user_id": user_id,
                "title": title,
                "content": content,
                "source": source,
            }
        )
        return {
            "id": 501,
            "title": title,
            "source": source,
        }

    def search(
        self,
        *,
        user_id,
        query,
        threshold,
        limit,
        rerank,
        candidate_limit,
    ):
        self.search_calls.append(
            {
                "user_id": user_id,
                "query": query,
                "threshold": threshold,
                "limit": limit,
                "rerank": rerank,
                "candidate_limit": candidate_limit,
            }
        )
        if query in self.empty_queries:
            return []

        return [
            {
                "document_id": 501,
                "title": "Private Knowledge",
                "source": "NOVA conversation",
                "chunk_index": 0,
                "content": (
                    "NOVA should feel like a natural personal companion, "
                    "not a traditional chatbot."
                ),
                "similarity": 0.91,
            }
        ]


def test_private_knowledge_save_bypasses_llm_and_persists_directly():
    service, conversation, _execution, llm, _memory = _service()
    knowledge = FakeKnowledgeService()
    service.knowledge_service = knowledge

    result = service.execute_message(
        user_id="user-1",
        message=(
            "Add this to my private knowledge: "
            "NOVA should feel like a natural personal companion, "
            "not a traditional chatbot."
        ),
    )

    assert llm.companion_calls == []
    assert knowledge.create_calls == [
        {
            "user_id": "user-1",
            "title": "Private Knowledge",
            "content": (
                "NOVA should feel like a natural personal companion, "
                "not a traditional chatbot."
            ),
            "source": "NOVA conversation",
        }
    ]
    assert result["understanding"]["intent"] == "knowledge"
    assert result["memory_action"] is None
    assert "saved that to your private knowledge" in result["response"]
    assert conversation.saved_messages[-1][3] == result["response"]


def test_private_knowledge_question_uses_a_focused_retrieval_fallback():
    service, conversation, _execution, llm, _memory = _service()
    knowledge = FakeKnowledgeService()
    knowledge.empty_queries.add("how NOVA should feel?")
    service.knowledge_service = knowledge

    result = service.execute_message(
        user_id="user-1",
        message=(
            "What does my private knowledge say about "
            "how NOVA should feel?"
        ),
    )

    assert llm.companion_calls == []
    assert knowledge.search_calls == [
        {
            "user_id": "user-1",
            "query": "how NOVA should feel?",
            "threshold": 0.60,
            "limit": 8,
            "rerank": True,
            "candidate_limit": 24,
        },
        {
            "user_id": "user-1",
            "query": "NOVA should feel",
            "threshold": 0.45,
            "limit": 8,
            "rerank": True,
            "candidate_limit": 24,
        },
    ]
    assert "natural personal companion" in result["response"]
    assert result["knowledge_sources"][0]["document_id"] == 501
    assert conversation.saved_messages[-1][3] == result["response"]


def test_private_knowledge_search_bypasses_llm_and_returns_grounded_source():
    service, conversation, _execution, llm, _memory = _service()
    knowledge = FakeKnowledgeService()
    service.knowledge_service = knowledge

    result = service.execute_message(
        user_id="user-1",
        message=(
            "Search my knowledge for information about "
            "NOVA being a personal companion."
        ),
    )

    assert llm.companion_calls == []
    assert knowledge.search_calls == [
        {
            "user_id": "user-1",
            "query": "information about NOVA being a personal companion.",
            "threshold": 0.60,
            "limit": 8,
            "rerank": True,
            "candidate_limit": 24,
        }
    ]
    assert "[Source 1] Private Knowledge" in result["response"]
    assert "natural personal companion" in result["response"]
    assert result["knowledge_sources"][0]["document_id"] == 501
    assert conversation.saved_messages[-1][3] == result["response"]



def test_tomorrow_workload_questions_use_full_graph_not_fast_llm_path():
    messages = (
        "What do I need to work on tomorrow?",
        "What should I work on tomorrow?",
        "What do I have to work on tomorrow?",
        "What do I need to do tomorrow?",
        "What should I do tomorrow?",
        "What work do I have tomorrow?",
        "What tasks do I have tomorrow?",
    )

    for message in messages:
        assert ConversationExecutionService._is_fast_conversation(
            message,
            history=[],
        ) is False
@pytest.mark.parametrize("use_voice_path", [False, True])
def test_source_backed_voice_assistant_comparison_uses_full_graph(use_voice_path):
    service, _conversation, execution, llm, _memory = _service()
    message = (
        "Which companies currently offer the strongest consumer AI voice assistants? "
        "Compare their strengths and limitations using recent reliable web sources. "
        "Include a source link and publication date for each major claim."
    )

    if use_voice_path:
        result = service.execute_voice_message(user_id="user-1", message=message)
    else:
        result = service.execute_message(user_id="user-1", message=message)

    assert result["response"] == "NOVA response"
    assert len(execution.calls) == 1
    assert llm.companion_calls == []
    assert llm.voice_calls == []
@pytest.mark.parametrize(
    "message",
    [
        "Mera naam Example hai.",
        "Example naam hai Example.",
        "\u092e\u0947\u0930\u093e \u0928\u093e\u092e \u0938\u0930\u094b\u091c \u0939\u0948",
        "\u0645\u06cc\u0631\u0627 \u0646\u0627\u0645 \u0645\u062b\u0627\u0644 \u06c1\u06d2",
        "Pyar se mujhe Rishi bulate hain.",
        "\u067e\u06cc\u0627\u0631 \u0633\u06d2 \u0645\u062c\u06be\u06d2 \u0631\u0634\u06cc \u0628\u0644\u0627\u062a\u06d2 \u06c1\u06cc\u06ba",
    ],
)
def test_voice_identity_statements_are_candidates_for_long_term_memory(message):
    assert ConversationExecutionService._is_memory_candidate(message)


def test_profile_question_uses_saved_identity_and_filters_conflicting_semantic_names():
    service, _conversation, _execution, _llm, memory = _service()
    memory.profile_memories = [
        {
            "memory": "The user's nickname is Rishi.",
            "category": "identity",
            "importance": "medium",
        },
        {
            "memory": "The user's name is Example.",
            "category": "identity",
            "importance": "high",
        },
        {
            "memory": "The user is building a personal assistant.",
            "category": "project",
            "importance": "medium",
        },
    ]
    memory.similar_memories = [
        {
            "memory": "User's name is an old conflicting name.",
            "category": "identity",
            "importance": "high",
        },
        {
            "memory": "The user likes voice conversations.",
            "category": "preference",
            "importance": "medium",
        },
    ]

    context = service._conversation_memory_context(
        user_id="user-1",
        message="Mera naam kya hai?",
    )

    assert "Example" in context
    assert "old conflicting name" not in context
    assert "voice conversations" in context
    assert "personal assistant" not in context


@pytest.mark.parametrize(
    "message",
    [
        "What tasks do I have?",
        "What reminders have I set?",
        "Show me my saved tasks and reminders.",
    ],
)
def test_voice_queries_for_saved_tasks_and_reminders_use_persistent_action_path(message):
    service, _conversation, execution, llm, _memory = _service()

    service.execute_voice_message(
        user_id="user-1",
        message=message,
        conversation_id=73,
    )

    assert len(execution.calls) == 1
    assert execution.calls[0]["conversation_id"] == 73
    assert llm.voice_calls == []



def test_english_and_devanagari_task_list_requests_bypass_voice_fast_path():
    messages = (
        "List all of my tasks.",
        "List my saved tasks.",
        "\u092e\u0947\u0930\u0947 \u0938\u093e\u0930\u0947 \u091f\u093e\u0938\u094d\u0915 \u0932\u093f\u0938\u094d\u091f \u0915\u0930\u094b\u0964",
        "\u092e\u0947\u0930\u0947 \u0938\u093e\u0930\u0947 \u091f\u093e\u0938\u094d\u0915 \u0915\u0940 \u0938\u0942\u091a\u0940 \u0926\u093f\u0916\u093e\u0913\u0964",
        "\u0915\u094d\u092f\u093e \u092e\u0947\u0930\u0947 \u0915\u094b\u0908 \u091f\u093e\u0938\u094d\u0915 \u0939\u0948\u0902?",
    )

    for message in messages:
        assert not ConversationExecutionService._is_fast_conversation(message), message



def test_mixed_devanagari_website_command_never_uses_generic_fast_chat_path():
    messages = (
        "\u0905\u091a\u094d\u091b\u093e, Wikipedia \u0913\u092a\u0928 \u0915\u0930\u0928\u093e\u0964",
        "Acha, Wikipedia \u0913\u092a\u0928 \u0915\u0930\u0928\u093e \u0939\u0948\u0964",
        "\u0905\u091a\u094d\u091b\u093e, Notepad \u0913\u092a\u0928 \u0915\u0930\u0928\u093e \u0939\u0948\u0964",
        "\u0939\u093e\u0902, Notepad \u0913\u092a\u0928 \u0915\u0930 \u0926\u094b\u0964",
        "\u0924\u0941\u092e \u0916\u0941\u0926 \u091c\u093e\u0915\u0930 \u0935\u0939\u093e\u0902 \u092a\u0930 \u0938\u0930\u094d\u091a \u0915\u0930\u094b \u0928\u093e \u092e\u0942\u0935\u0940\u091c\u0964",
    )
    for message in messages:
        assert not ConversationExecutionService._is_fast_conversation(message, history=[]), message


def test_youtube_playback_requests_never_use_generic_fast_chat_path():
    messages = (
        "YouTube par Pal Pal song chalayen",
        "YouTube par Pal Pal song chalao",
        "\u0905\u091a\u094d\u091b\u093e YouTube \u092a\u0930 \u092a\u0932-\u092a\u0932 \u0938\u0949\u0928\u094d\u0917 \u091a\u0932\u093e\u0928\u093e\u0964",
    )
    for message in messages:
        assert not ConversationExecutionService._is_fast_conversation(
            message, history=[]
        ), message


def test_desktop_commands_never_use_generic_fast_chat_path():
    messages = (
        "Open Notepad",
        "Open Local Drive C",
        "Local Drive C open karna",
        "Acha Notepad open kar lo.",
        "Acha Wikipedia open kar lo.",
        "Open https://example.com",
        "Search my files for resume",
        "Open Documents",
        "Google search for NOVA AI",
        "Find and list my CV files on my device.",
        "Meri downloaded files dikhao",
        "Downloads dikhao",
        "List files in Downloads",
        "Meri emails dikhao",
        "Meri inbox check karo",
        "Spotify kholo aur Pal Pal chalao",
        "What is on my screen?",
        "What's on my screen?",
        "Spotify par jao aur Pal Pal song chalao",
        "Spotify पर जाओ और पल पल सॉन्ग चलाओ।",
        "MrBeast ki latest video chalao",
        "MrBeast ne jo like latest video upload ki hai na usko chalao",
        "YouTube par jao aur MrBeast ki latest video chalao",
        "YouTube mein pal-pal song chalana mere liye",
        "YouTube mein पल-पल सॉन्ग चलाना मेरे लिए।",
        "मेरे स्क्रीन पर अभी क्या ओपन है?",
        "This PC open karo",
        "Cycle bin open karo",
        "Recycle Bin open karo",
        "Achha meri CV dekho wo mujhe batao kaun kaun si hai?",
        "\u0905\u091a\u094d\u091b\u093e \u0932\u094b\u0915\u0932 \u0921\u093f\u0938\u094d\u0915 \u0938\u0940 \u0913\u092a\u0928 \u0915\u0930\u0928\u093e\u0964",
        "Power PowerPoint open karna.",
        "World open karna file.",
        "Spotify kholo",
        "VS Code open karna.",
        "What's open on my screen?",
        "What's on my screen right now?",
        "What open on my screen right now?",
        "Inspect the desktop",
        "Screen pe kya hai",
        "Meri screen dikhao",
        "स्क्रीन दिखाओ",
        "डेस्कटॉप पर क्या दिख रहा है",
        "Click Search in YouTube",
        "Type Interstellar into Search",
        "Press CTRL+L in Opera",
        "Search button pe click kar do",
        "YouTube mein Search button pe click kar do",
        "Search bar mein Interstellar likh do",
        "CTRL+L dabao",
        "YouTube खोलो और इंटरस्टेलर साउंडट्रैक चलाओ।",
        "YouTube par MrBeast ki koi latest video chalao.",
        "YouTube kholo aur Interstellar soundtrack chalao.",
        "Play Interstellar Soundtrack on YouTube",
        "YouTube par song search karo.",
    )

    for message in messages:
        assert not ConversationExecutionService._is_fast_conversation(
            message,
            history=[],
        ), message

def test_execute_voice_message_routes_mixed_devanagari_website_command_to_graph():
    service, _conversation, execution, llm, _memory = _service()
    message = "\u0905\u091a\u094d\u091b\u093e, Wikipedia \u0913\u092a\u0928 \u0915\u0930\u0928\u093e\u0964"
    result = service.execute_voice_message(user_id="user-1", message=message)
    assert result["response"] == "NOVA response"
    assert len(execution.calls) == 1
    assert execution.calls[0]["user_message"] == message
    assert llm.voice_calls == []
    assert llm.companion_calls == []


@pytest.mark.parametrize(
    "message",
    [
        "I said open Wikipedia.",
        "I'm doing great. Wikipedia open karo.",
        "Okay, open Wikimedia. Wikipedia",
        "Acha Wikipedia open kar lo.",
        "Acha Notepad open kar lo.",
        "Acha, Wikipedia \u0913\u092a\u0928 \u0915\u0930\u0928\u093e \u0939\u0948\u0964",
        "Launch Spotify",
    ],
)
def test_execute_voice_message_routes_named_website_commands_to_full_execution_graph(message):
    service, _conversation, execution, llm, _memory = _service()

    result = service.execute_voice_message(
        user_id="user-1",
        message=message,
    )

    assert result["response"] == "NOVA response"
    assert len(execution.calls) == 1
    assert execution.calls[0]["user_message"] == message
    assert llm.voice_calls == []
    assert llm.companion_calls == []


def test_persisted_task_list_reports_missing_requested_title():
    from services.conversation_execution_service import _format_persisted_task_list_response

    tool_result = {
        "tool": "task",
        "action": "list",
        "success": True,
        "result": {
            "tasks": [
                {
                    "title": "Nova Live Test task. 1021 ko due date mat lagana",
                    "status": "pending",
                    "priority": "medium",
                    "due_at": None,
                }
            ]
        },
    }
    response = _format_persisted_task_list_response(
        tool_result,
        "Meri tamam tasks ki list dikhao aur check karo ke us mein Nova Light test shamil hai ya nahi.",
    )

    assert response is not None
    assert "exact 'nova light test' task saved list mein nahi mila" in response.lower()
    assert "Nova Live Test task. 1021 ko due date mat lagana" in response


def test_persisted_task_list_confirms_requested_title_when_saved():
    from services.conversation_execution_service import _format_persisted_task_list_response

    tool_result = {
        "tool": "task",
        "action": "list",
        "success": True,
        "result": {
            "tasks": [
                {
                    "title": "Nova Live Test task. 1021 ko due date mat lagana",
                    "status": "pending",
                    "priority": "medium",
                    "due_at": None,
                }
            ]
        },
    }
    response = _format_persisted_task_list_response(
        tool_result,
        "Mere tasks check karo ke Nova Live Test task list mein hai ya nahi.",
    )

    assert response is not None
    assert "'nova live test' saved task list mein mila" in response.lower()
    assert "exact 'nova live test' task saved list mein nahi mila" not in response.lower()


def test_calendar_confirmation_follow_up_bypasses_fast_path_without_pending_row():
    history = [
        {
            "role": "user",
            "content": (
                'Create a calendar event Friday at 4 PM called "Nova Voice Calendar Test".'
            ),
        },
        {
            "role": "assistant",
            "content": (
                "I can add that event to your Google Calendar. Please confirm."
            ),
        },
    ]

    for reply in ("confirm", "yes", "Yes add kar do", "haan kar do"):
        assert not ConversationExecutionService._is_fast_conversation(
            reply,
            history=history,
        ), reply


def test_calendar_confirmation_follow_up_does_not_capture_unrelated_chat():
    history = [
        {
            "role": "user",
            "content": "Create a calendar event Friday at 4 PM called NOVA test.",
        },
        {
            "role": "assistant",
            "content": "The calendar event is saved successfully.",
        },
    ]

    assert ConversationExecutionService._is_fast_conversation(
        "Tell me a joke.",
        history=history,
    )
    assert not ConversationExecutionService._has_unfinished_calendar_confirmation_context(
        "confirm",
        history=history,
    )


def test_execute_message_fails_closed_for_calendar_approval_without_pending_confirmation():
    service, conversation, execution, llm, _memory = _service()
    conversation.history = [
        {
            "role": "user",
            "content": 'Create a calendar event Friday at 4 PM called "Nova Voice Calendar Test".',
        },
        {
            "role": "assistant",
            "content": "I can add that event to your Google Calendar. Please confirm.",
        },
    ]

    result = service.execute_message(
        user_id="user-1",
        message="confirm",
    )

    assert "NOT created" in result["response"]
    assert result["tool_result"]["success"] is False
    assert result["tool_result"]["error"] == "No pending Calendar confirmation exists."
    assert execution.calls == []
    assert llm.companion_calls == []


def test_calendar_confirmation_context_recognizes_devanagari_voice_reply():
    history = [
        {
            "role": "user",
            "content": (
                "Nova 23 October 2026 ko 4 PM se 4:30 PM tak Google Calendar "
                "mein event create karo exact title Nova calendar confirmation retest 1021"
            ),
        },
        {
            "role": "assistant",
            "content": (
                "Sure thing! I can add an event for Friday at 4:00 p.m. "
                "May I go ahead and create it on your calendar?"
            ),
        },
    ]

    assert ConversationExecutionService._has_unfinished_calendar_confirmation_context(
        "यस कर दो।",
        history=history,
    )
    assert not ConversationExecutionService._is_fast_conversation(
        "यस कर दो।",
        history=history,
    )


def test_saved_profile_question_wording_is_routed_to_profile_memory():
    assert ConversationExecutionService._profile_memory_query_type(
        "Read-only QA: what name do you have saved for me? Use the stored memory only."
    ) == "name"
    assert ConversationExecutionService._profile_memory_query_type(
        "Read-only QA: what do you remember about my NOVA project?"
    ) == "profile"


def test_persisted_task_list_response_answers_active_task_count():
    result = {
        "success": True,
        "tool": "task",
        "action": "list",
        "error": None,
        "result": {
            "tasks": [
                {"title": "A", "status": "pending", "priority": "low"},
                {"title": "B", "status": "completed", "priority": "medium"},
                {"title": "C", "status": "in_progress", "priority": "high"},
            ]
        },
    }
    response = _format_persisted_task_list_response(
        result,
        user_message="Read-only QA: tell me the count of active tasks.",
    )
    assert response == "Aapki saved task list mein 2 active tasks hain."

    result["result"]["tasks"] = []
    assert _format_persisted_task_list_response(
        result,
        user_message="Read-only QA: tell me the count of active tasks.",
    ) == "Aapki saved task list mein 0 active tasks hain."


def test_saved_knowledge_questions_bypass_fast_chat_path():
    message = (
        "What exact QA sample value is stored in NOVA QA TEMP 20261026? "
        "Please include the source title."
    )
    assert not ConversationExecutionService._is_fast_conversation(
        message,
        history=[],
    )
    assert not ConversationExecutionService._is_fast_conversation(
        "What does my private knowledge say about LangGraph?",
        history=[],
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Calculate 17 * 6. Reply with only the number.", "102"),
        ("What is 7 plus 8?", "15"),
        ("Compute (8 + 4) / 3.", "4"),
        ("Calculate 17 times 6.", "102"),
        ("What is 7 divided by 2?", "3.5"),
    ],
)
def test_simple_arithmetic_response_is_deterministic(message, expected):
    assert _simple_arithmetic_response(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "Calculate 17 * 6 and email the result to me.",
        "Calculate 1 / 0.",
        "What is the latest cricket score for 17?",
        "What is 2026-10-27?",
        "What is 12/31/2026?",
        "Calculate __import__('os').system('whoami')",
    ],
)
def test_simple_arithmetic_response_rejects_ambiguous_or_unsafe_requests(message):
    assert _simple_arithmetic_response(message) is None


def test_execute_message_answers_simple_arithmetic_without_llm_guessing():
    service, conversation, execution, llm, _memory = _service()

    result = service.execute_message(
        user_id="user-1",
        message="Calculate 17 * 6. Reply with only the number.",
    )

    assert result["response"] == "102"
    assert execution.calls == []
    assert llm.companion_calls == []
    assert conversation.saved_messages[-2:] == [
        ("user-1", 42, "user", "Calculate 17 * 6. Reply with only the number."),
        ("user-1", 42, "assistant", "102"),
    ]


def test_execute_voice_message_answers_simple_arithmetic_without_llm_guessing():
    service, conversation, execution, llm, _memory = _service()

    result = service.execute_voice_message(
        user_id="user-1",
        message="Calculate 17 * 6.",
    )

    assert result["response"] == "102"
    assert execution.calls == []
    assert llm.voice_calls == []
    assert conversation.saved_messages[-2:] == [
        ("user-1", 42, "user", "Calculate 17 * 6."),
        ("user-1", 42, "assistant", "102"),
    ]

