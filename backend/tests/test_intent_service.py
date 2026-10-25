from types import SimpleNamespace

import services.intent_service as intent_service_module
from services.intent_service import IntentService


def make_service_without_llm():
    service = IntentService.__new__(
        IntentService
    )
    return service


def test_validate_reminder_defaults_missing_action_to_create():
    service = make_service_without_llm()

    result = {
        "intent": "reminder",
        "task": "submit CV",
        "reminder_action": None,
        "requires_tool": True,
    }

    validated = service._validate_result(result)

    assert validated["intent"] == "reminder"
    assert validated["reminder_action"] == "create"
    assert validated["requires_tool"] is True


def test_validate_reminder_preserves_update_action():
    service = make_service_without_llm()

    result = {
        "intent": "reminder",
        "task": "submit CV",
        "reminder_action": "update",
        "reminder_reference": "CV reminder",
        "scheduled_at": "2026-09-16T15:00:00",
        "requires_tool": True,
    }

    validated = service._validate_result(result)

    assert validated["reminder_action"] == "update"
    assert validated["reminder_reference"] == "CV reminder"
    assert validated["scheduled_at"] == "2026-09-16T15:00:00"


def test_validate_reminder_accepts_complete_action():
    service = make_service_without_llm()

    result = {
        "intent": "reminder",
        "reminder_action": "complete",
        "reminder_reference": "submit CV",
        "requires_tool": True,
    }

    validated = service._validate_result(result)

    assert validated["reminder_action"] == "complete"
    assert validated["reminder_reference"] == "submit CV"


def test_validate_reminder_accepts_cancel_action():
    service = make_service_without_llm()

    result = {
        "intent": "reminder",
        "reminder_action": "cancel",
        "reminder_id": 8,
        "requires_tool": True,
    }

    validated = service._validate_result(result)

    assert validated["reminder_action"] == "cancel"
    assert validated["reminder_id"] == 8


def test_validate_reminder_accepts_delete_action():
    service = make_service_without_llm()

    result = {
        "intent": "reminder",
        "reminder_action": "delete",
        "reminder_id": 9,
        "requires_tool": True,
    }

    validated = service._validate_result(result)

    assert validated["reminder_action"] == "delete"
    assert validated["reminder_id"] == 9


def test_validate_task_update_preserves_update_fields():
    service = make_service_without_llm()

    result = {
        "intent": "task",
        "task_action": "update",
        "task_reference": "practice LangGraph",
        "priority": "high",
        "scheduled_at": "2026-09-16T18:00:00",
        "requires_tool": True,
    }

    validated = service._validate_result(result)

    assert validated["task_action"] == "update"
    assert validated["task_reference"] == "practice LangGraph"
    assert validated["priority"] == "high"
    assert validated["scheduled_at"] == "2026-09-16T18:00:00"


def test_validate_chat_does_not_require_tool():
    service = make_service_without_llm()

    result = {
        "intent": "chat",
        "requires_tool": False,
    }

    validated = service._validate_result(result)

    assert validated["intent"] == "chat"
    assert validated["requires_tool"] is False


def test_validate_goal_change_as_chat_is_still_safe():
    """
    _validate_result() should preserve the LLM's chosen
    intent rather than inventing a new intent type.

    Goal-change understanding itself is tested separately
    with the live LLM.
    """

    service = make_service_without_llm()

    result = {
        "intent": "chat",
        "task": None,
        "task_reference": None,
        "task_action": None,
        "task_id": None,
        "priority": None,
        "reminder_action": None,
        "reminder_reference": None,
        "reminder_id": None,
        "time": None,
        "scheduled_at": None,
        "emotion": "neutral",
        "tone": "friendly",
        "visual": "none",
        "action": None,
        "requires_tool": False,
    }

    validated = service._validate_result(result)

    assert validated["intent"] == "chat"
    assert validated["requires_tool"] is False


def test_validate_goal_change_does_not_create_tool_fields():
    """
    A normal conversational goal-change statement should not
    accidentally become a task or reminder operation.
    """

    service = make_service_without_llm()

    result = {
        "intent": "chat",
        "task": "become a Machine Learning Engineer",
        "task_action": None,
        "task_reference": None,
        "task_id": None,
        "priority": None,
        "reminder_action": None,
        "reminder_reference": None,
        "reminder_id": None,
        "requires_tool": False,
    }

    validated = service._validate_result(result)

    assert validated["intent"] == "chat"
    assert validated["task_action"] is None
    assert validated["task_reference"] is None
    assert validated["task_id"] is None
    assert validated["reminder_action"] is None
    assert validated["reminder_reference"] is None
    assert validated["reminder_id"] is None
    assert validated["requires_tool"] is False

def test_validate_web_search_request():
    service = make_service_without_llm()

    result = {
        "intent": "web",
        "web_action": "search",
        "web_topic": "news",
        "web_time_range": "day",
        "query": "latest AI news",
        "max_results": 5,
        "requires_tool": True,
    }

    validated = service._validate_result(result)

    assert validated["intent"] == "web"
    assert validated["web_action"] == "search"
    assert validated["web_topic"] == "news"
    assert validated["web_time_range"] == "day"
    assert validated["query"] == "latest AI news"
    assert validated["max_results"] == 5
    assert validated["requires_tool"] is True


def test_validate_invalid_web_action_defaults_to_search():
    service = make_service_without_llm()

    result = {
        "intent": "web",
        "web_action": "crawl",
        "web_topic": "invalid",
        "web_time_range": "hour",
        "query": "AI",
        "requires_tool": False,
    }

    validated = service._validate_result(result)

    assert validated["intent"] == "web"
    assert validated["web_action"] == "search"
    assert validated["web_topic"] == "general"
    assert validated["web_time_range"] is None
    assert validated["requires_tool"] is True

def test_latest_developments_request_forces_news_day_search():
    service = make_service_without_llm()

    result = {
        "intent": "chat",
        "query": None,
        "web_action": None,
        "web_topic": None,
        "web_time_range": None,
        "requires_tool": False,
    }

    routed = service._force_fresh_web_research(
        message="Search the web for the latest developments in AI voice assistants.",
        result=result,
    )

    assert routed["intent"] == "web"
    assert routed["web_action"] == "search"
    assert routed["web_topic"] == "news"
    assert routed["web_time_range"] == "day"
    assert routed["requires_tool"] is True


def test_latest_ai_news_request_overrides_an_unrelated_classifier_query():
    service = make_service_without_llm()
    result = {
        "intent": "chat",
        "query": "McKinsey Technology Trends Outlook 2026",
        "web_action": None,
        "web_topic": None,
        "web_time_range": None,
        "requires_tool": False,
    }

    routed = service._force_fresh_web_research(
        message=(
            "Search the web for the latest AI news today. Give me the "
            "three most important developments with source links and dates."
        ),
        result=result,
    )

    assert routed["intent"] == "web"
    assert routed["web_action"] == "search"
    assert routed["web_topic"] == "news"
    assert routed["web_time_range"] == "day"
    assert routed["query"] == "latest AI news"
    assert routed["requires_tool"] is True


def test_explicit_recent_web_sources_override_planning_classification():
    service = make_service_without_llm()
    message = (
        "Which companies currently offer the strongest consumer AI "
        "voice-assistant experiences? Compare their real strengths and "
        "limitations using recent, reliable web sources. Include a source "
        "link and publication date for each major claim. Distinguish verified "
        "capabilities from predictions, avoid outdated products or unsupported "
        "rankings, and tell me honestly if the evidence is insufficient to "
        "name a clear winner."
    )
    result = {
        "intent": "planning",
        "query": None,
        "web_action": None,
        "web_topic": None,
        "web_time_range": None,
        "requires_tool": False,
    }

    routed = service._force_fresh_web_research(
        message=message,
        result=result,
    )

    assert routed["intent"] == "web"
    assert routed["web_action"] == "search"
    assert routed["web_topic"] == "general"
    assert routed["query"] == message
    assert routed["requires_tool"] is True


def test_fresh_information_question_forces_web_search():
    service = make_service_without_llm()

    result = {
        "intent": "question",
        "query": None,
        "web_action": None,
        "web_topic": None,
        "web_time_range": None,
        "requires_tool": False,
    }

    routed = service._force_fresh_web_research(
        message="What's the latest FastAPI release?",
        result=result,
    )

    assert routed["intent"] == "web"
    assert routed["web_action"] == "search"
    assert routed["web_topic"] == "general"
    assert routed["web_time_range"] is None
    assert routed["query"] == "What's the latest FastAPI release?"
    assert routed["action"] == "search"
    assert routed["requires_tool"] is True


def test_fresh_news_request_forces_news_day_search():
    service = make_service_without_llm()

    result = {
        "intent": "chat",
        "query": None,
        "web_action": None,
        "web_topic": None,
        "web_time_range": None,
        "requires_tool": False,
    }

    routed = service._force_fresh_web_research(
        message="What are today's AI news headlines?",
        result=result,
    )

    assert routed["intent"] == "web"
    assert routed["web_action"] == "search"
    assert routed["web_topic"] == "news"
    assert routed["web_time_range"] == "day"
    assert routed["query"] == "latest AI news"
    assert routed["requires_tool"] is True


def test_fresh_finance_request_forces_finance_search():
    service = make_service_without_llm()

    result = {
        "intent": "question",
        "query": "USD to PKR rate",
        "web_action": None,
        "web_topic": None,
        "web_time_range": None,
        "requires_tool": False,
    }

    routed = service._force_fresh_web_research(
        message="What is the current USD to PKR exchange rate?",
        result=result,
    )

    assert routed["intent"] == "web"
    assert routed["web_action"] == "search"
    assert routed["web_topic"] == "finance"
    assert routed["web_time_range"] is None
    assert routed["query"] == "USD to PKR rate"
    assert routed["requires_tool"] is True


def test_personal_task_today_is_not_forced_to_web():
    service = make_service_without_llm()

    result = {
        "intent": "chat",
        "query": None,
        "web_action": None,
        "web_topic": None,
        "web_time_range": None,
        "requires_tool": False,
    }

    routed = service._force_fresh_web_research(
        message="Remind me to submit my CV today.",
        result=result,
    )

    assert routed["intent"] == "chat"
    assert routed["requires_tool"] is False


def test_current_personal_task_is_not_forced_to_web():
    service = make_service_without_llm()

    result = {
        "intent": "question",
        "query": "my current task",
        "web_action": None,
        "web_topic": None,
        "web_time_range": None,
        "requires_tool": False,
    }

    routed = service._force_fresh_web_research(
        message="What is my current task?",
        result=result,
    )

    assert routed["intent"] == "question"
    assert routed["requires_tool"] is False


def test_word_boundary_prevents_now_substring_false_positive():
    service = make_service_without_llm()

    result = {
        "intent": "chat",
        "query": None,
        "web_action": None,
        "web_topic": None,
        "web_time_range": None,
        "requires_tool": False,
    }

    routed = service._force_fresh_web_research(
        message="I don't know how to improve my Python.",
        result=result,
    )

    assert routed["intent"] == "chat"
    assert routed["requires_tool"] is False


def test_analyze_applies_deterministic_fresh_web_routing(monkeypatch):
    service = make_service_without_llm()

    class FakeMessage:
        content = '{"intent":"question","query":null,"requires_tool":false}'

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    service.client = FakeClient()

    result = service.analyze(
        message="What's the latest FastAPI release?",
        history=[],
    )

    assert result["intent"] == "web"
    assert result["web_action"] == "search"
    assert result["query"] == "What's the latest FastAPI release?"
    assert result["requires_tool"] is True



def test_analyze_bounds_intent_payload_and_completion_tokens():
    service = make_service_without_llm()
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"intent":"chat","requires_tool":false}'
                        )
                    )
                ]
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    history = [{"role": "user", "content": "important context " * 200}]

    result = service.analyze("Hey Nova", history=history)

    prompt_chars = sum(len(item.get("content", "")) for item in captured["messages"])
    assert prompt_chars < 6_000
    assert captured["max_completion_tokens"] == 384
    assert result["intent"] == "chat"
    assert result["requires_tool"] is False


def test_delete_existing_task_is_classified_without_provider_and_keeps_exact_reference():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "An exact task-delete command must not depend on the LLM provider."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )
    result = service.analyze(
        message='Delete the task "Finish NOVA frontend QA".',
        history=[],
    )

    assert result["intent"] == "task"
    assert result["task_action"] == "delete"
    assert result["task_reference"] == "Finish NOVA frontend QA"
    assert result["requires_tool"] is True
    assert result["task_id"] is None


def test_intent_service_uses_bounded_llm_settings(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        intent_service_module,
        "OpenAI",
        FakeOpenAI,
    )
    monkeypatch.setattr(
        intent_service_module,
        "get_llm_settings",
        lambda: SimpleNamespace(
            llm_request_timeout_seconds=7.5,
            llm_max_retries=1,
        ),
    )

    service = IntentService()

    assert service.settings.llm_request_timeout_seconds == 7.5
    assert service.settings.llm_max_retries == 1
    assert captured["timeout"] == 7.5
    assert captured["max_retries"] == 0


def test_analyze_returns_safe_unavailable_state_for_provider_failure(
    monkeypatch,
):
    service = make_service_without_llm()

    class FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError("provider rate limit")

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=FailingCompletions()
        )
    )

    monkeypatch.setattr(
        intent_service_module,
        "is_llm_provider_error",
        lambda exc: True,
    )

    result = service.analyze(
        message="Add this to my private knowledge: NOVA should feel natural.",
        history=[],
    )

    assert result["intent"] == "chat"
    assert result["requires_tool"] is False
    assert result["llm_provider_unavailable"] is True


def test_analyze_resolves_clear_reminder_without_calling_llm(
    monkeypatch,
):
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "Clear reminders must not depend on the LLM provider."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )

    result = service.analyze(
        message="Remind me tomorrow at 10 AM to check my NOVA progress.",
        history=[],
    )

    assert result["intent"] == "reminder"
    assert result["reminder_action"] == "create"
    assert result["task"] == "check my NOVA progress"
    assert result["requires_tool"] is True
    assert result["scheduled_at"].endswith("+05:00")
    assert "llm_provider_unavailable" not in result


def test_analyze_resolves_clear_task_without_calling_llm(
    monkeypatch,
):
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "Clear tasks must not depend on the LLM provider."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )

    result = service.analyze(
        message='Create a task called "Finish NOVA frontend QA" with high priority and due tomorrow.',
        history=[],
    )

    assert result["intent"] == "task"
    assert result["task_action"] == "create"
    assert result["task"] == "Finish NOVA frontend QA"
    assert result["priority"] == "high"
    assert result["requires_tool"] is True
    assert result["scheduled_at"].endswith("+05:00")
    assert "llm_provider_unavailable" not in result


def test_analyze_resolves_task_titled_with_no_due_date_without_calling_llm():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "Clear task creation must not depend on the LLM provider."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )

    result = service.analyze(
        message='Create a task titled "Finish NOVA frontend QA" with medium priority and no due date.',
        history=[],
    )

    assert result["intent"] == "task"
    assert result["task_action"] == "create"
    assert result["task"] == "Finish NOVA frontend QA"
    assert result["priority"] == "medium"
    assert result["scheduled_at"] is None
    assert result["requires_tool"] is True
    assert "llm_provider_unavailable" not in result


def test_analyze_resolves_another_task_without_calling_llm(
    monkeypatch,
):
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "Clear additional tasks must not depend on the LLM provider."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )

    result = service.analyze(
        message='Create another task called "Review AI Engineer applications" with medium priority.',
        history=[],
    )

    assert result["intent"] == "task"
    assert result["task_action"] == "create"
    assert result["task"] == "Review AI Engineer applications"
    assert result["priority"] == "medium"
    assert result["requires_tool"] is True
    assert result["scheduled_at"] is None
    assert "llm_provider_unavailable" not in result


def test_analyze_keeps_unknown_request_non_executable_when_provider_is_unavailable(
    monkeypatch,
):
    service = make_service_without_llm()

    class FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError("provider rate limit")

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=FailingCompletions()
        )
    )

    monkeypatch.setattr(
        intent_service_module,
        "is_llm_provider_error",
        lambda exc: True,
    )

    result = service.analyze(
        message="Tell me something interesting about AI.",
        history=[],
    )

    assert result["intent"] == "chat"
    assert result["requires_tool"] is False
    assert result["llm_provider_unavailable"] is True


def test_analyze_recovers_planning_duration_follow_up_from_history_when_provider_is_unavailable(
    monkeypatch,
):
    service = make_service_without_llm()

    class FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError("provider rate limit")

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=FailingCompletions()
        )
    )

    monkeypatch.setattr(
        intent_service_module,
        "is_llm_provider_error",
        lambda exc: True,
    )

    result = service.analyze(
        message="I only have three hours for focused work.",
        history=[
            {
                "role": "user",
                "content": (
                    "Help me plan tomorrow. I have to work on NOVA, "
                    "study AI, apply for jobs, and also get some rest."
                ),
            }
        ],
    )

    assert result["intent"] == "planning"
    assert result["requires_tool"] is False
    assert result["llm_provider_unavailable"] is True


def test_analyze_routes_ambiguous_send_reference_to_clarification_without_llm():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "Ambiguous send references must not depend on the LLM provider."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )

    result = service.analyze(
        message="Send that to him.",
        history=[
            {
                "role": "user",
                "content": "Search the latest news about OpenAI.",
            },
            {
                "role": "assistant",
                "content": "I searched the live web just now.",
            },
        ],
    )

    assert result["intent"] == "action"
    assert result["action"] == "send"
    assert result["clarification_required"] is True
    assert result["requires_tool"] is False
    assert "llm_provider_unavailable" not in result


def test_deterministic_fallback_routes_send_reference_variants_to_clarification():
    service = make_service_without_llm()

    for message in (
        "Send that to him.",
        "Send this to her!",
        "Send it to them?",
    ):
        result = service._deterministic_fallback(
            message=message,
            history=[{"role": "user", "content": "Previous request"}],
        )

        assert result["intent"] == "action"
        assert result["action"] == "send"
        assert result["clarification_required"] is True
        assert result["requires_tool"] is False


def test_analyze_routes_simple_email_to_self_without_llm():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "Clear email requests must not depend on the LLM provider."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )

    result = service.analyze(
        message="Send an email to myself saying \"NOVA test successful.\"",
        history=[],
    )

    assert result["intent"] == "email"
    assert result["email_action"] == "send"
    assert result["action"] == "send"
    assert result["recipient_reference"] == "self"
    assert result["to"] is None
    assert result["subject"] == "NOVA message"
    assert result["body"] == "NOVA test successful."
    assert result["requires_tool"] is True
    assert "llm_provider_unavailable" not in result


def test_deterministic_email_parses_explicit_recipient_and_body():
    service = make_service_without_llm()

    result = service._deterministic_fallback(
        message="Send an email to hr@example.com saying \"The interview update is ready.\"",
        history=[],
    )

    assert result["intent"] == "email"
    assert result["email_action"] == "send"
    assert result["action"] == "send"
    assert result["recipient_reference"] is None
    assert result["to"] == "hr@example.com"
    assert result["subject"] == "NOVA message"
    assert result["body"] == "The interview update is ready."
    assert result["requires_tool"] is True


def test_deterministic_email_normalizes_bracketed_recipient():
    service = make_service_without_llm()

    for recipient_syntax in (
        "[saroshqaiser4@gmail.com]",
        "<saroshqaiser4@gmail.com>",
        "saroshqaiser4@gmail.com",
    ):
        result = service._deterministic_fallback(
            message=(
                f"Send an email to {recipient_syntax} saying "
                "\"NOVA recipient email test successful.\""
            ),
            history=[],
        )

        assert result["intent"] == "email"
        assert result["email_action"] == "send"
        assert result["to"] == "saroshqaiser4@gmail.com"
        assert result["body"] == "NOVA recipient email test successful."


def test_deterministic_email_inbox_and_search_requests_route_without_llm():
    service = make_service_without_llm()

    cases = (
        ("Show me my latest emails", "list", None, False),
        ("Meri emails dikhao", "list", None, False),
        ("Meri inbox check karo", "list", None, False),
        ("Emails dikhao", "list", None, False),
        ("Check my unread emails", "list", "in:inbox is:unread", False),
        ("Search my emails for invoice", "search", "invoice", False),
        ("Summarize my latest emails", "list", None, True),
        ("Read my latest email", "list", None, True),
    )
    for message, expected_action, expected_query, expected_include_body in cases:
        result = service.analyze(message=message, history=[])

        assert result["intent"] == "email", message
        assert result["email_action"] == expected_action, message
        assert result["query"] == expected_query, message
        assert result["include_body"] is expected_include_body, message
        assert result["requires_tool"] is True, message
        assert "llm_provider_unavailable" not in result, message


def test_deterministic_important_email_queries_cover_recent_and_hindi_voice_phrasings():
    service = make_service_without_llm()
    cases = (
        ("Show me important emails", "in:inbox is:important", 5),
        ("Any important emails?", "in:inbox is:important", 5),
        ("Check my unread important emails", "in:inbox is:unread is:important", 5),
        ("Did I get any important emails today?", "in:inbox newer_than:1d", 10),
        ("Kya koi important email aayi hai?", "in:inbox newer_than:1d", 10),
        ("Aaj koi important email aayi hai kya?", "in:inbox newer_than:1d", 10),
        ("\u0915\u094d\u092f\u093e \u0915\u094b\u0908 \u091c\u0930\u0942\u0930\u0940 \u0908\u092e\u0947\u0932 \u0906\u0908 \u0939\u0948?", "in:inbox newer_than:1d", 10),
    )
    for message, expected_query, expected_limit in cases:
        result = service.analyze(message=message, history=[])
        assert result["intent"] == "email", message
        assert result["email_action"] == "list", message
        assert result["query"] == expected_query, message
        assert result["max_results"] == expected_limit, message
        assert result["include_body"] is False, message
        assert result["requires_tool"] is True, message
        assert "llm_provider_unavailable" not in result, message


def test_validate_email_get_preserves_only_valid_message_ids():
    service = make_service_without_llm()

    result = service._validate_result({
        "intent": "email",
        "email_action": "get",
        "message_id": "message_123",
        "requires_tool": True,
    })
    assert result["email_action"] == "get"
    assert result["message_id"] == "message_123"

    invalid = service._validate_result({
        "intent": "email",
        "email_action": "get",
        "message_id": "../other-user-message",
        "requires_tool": True,
    })
    assert invalid["email_action"] == "get"
    assert invalid["message_id"] is None


def test_deterministic_fresh_web_requests_cover_common_latest_news_phrasings():
    service = make_service_without_llm()

    messages = (
        ("What's the latest AI news today?", "latest AI news"),
        ("What are the latest AI developments?", "What are the latest AI developments?"),
        ("Give me the current AI news.", "latest AI news"),
        ("Show me today's AI headlines.", "latest AI news"),
        ("Search the web for the latest AI news.", "latest AI news"),
        ("What's the latest news in AI?", "latest AI news"),
    )

    for message, expected_query in messages:
        result = service._deterministic_fallback(
            message=message,
            history=[],
        )

        assert result["intent"] == "web"
        assert result["web_action"] == "search"
        assert result["web_topic"] == "news"
        assert result["requires_tool"] is True
        assert result["query"] == expected_query


def test_deterministic_source_based_voice_assistant_comparison_uses_broad_search():
    service = make_service_without_llm()
    message = (
        "Which companies currently offer the strongest consumer AI "
        "voice-assistant experiences? Compare their real strengths and "
        "limitations using recent, reliable web sources. Include a source "
        "link and publication date for each major claim. Distinguish verified "
        "capabilities from predictions, avoid outdated products or unsupported "
        "rankings, and tell me honestly if the evidence is insufficient to "
        "name a clear winner."
    )

    result = service._deterministic_fallback(
        message=message,
        history=[],
    )

    assert result["intent"] == "web"
    assert result["web_action"] == "search"
    assert result["web_topic"] == "news"
    assert result["web_time_range"] is None
    assert result["requires_tool"] is True
    assert "Gemini Live" in result["query"]
    assert "Alexa+" in result["query"]
    assert "ChatGPT Voice" in result["query"]


def test_analyze_recovers_latest_ai_news_when_llm_provider_is_unavailable(monkeypatch):
    calls = []

    class FailingCompletions:
        def create(self, **kwargs):
            calls.append(True)
            raise RuntimeError("simulated Groq 429")

    class FakeClient:
        chat = type(
            "Chat",
            (),
            {
                "completions": FailingCompletions(),
            },
        )()

    service = make_service_without_llm()
    service.client = FakeClient()

    monkeypatch.setattr(
        intent_service_module,
        "is_llm_provider_error",
        lambda exc: True,
    )

    result = service.analyze(
        message="What's the latest AI news today?",
        history=[],
    )

    assert result["intent"] == "web"
    assert result["web_action"] == "search"
    assert result["web_topic"] == "news"
    assert result["web_time_range"] == "day"
    assert result["requires_tool"] is True
    assert calls == []
    assert "llm_provider_unavailable" not in result


def test_analyze_resolves_current_weather_without_calling_llm():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "Clear weather requests must not depend on the LLM provider."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )

    result = service.analyze(
        message="What's the current weather in Lahore?",
        history=[],
    )

    assert result["intent"] == "web"
    assert result["web_action"] == "search"
    assert result["web_topic"] == "weather"
    assert result["query"] == "What's the current weather in Lahore?"
    assert result["requires_tool"] is True
    assert "llm_provider_unavailable" not in result


def test_force_fresh_web_research_routes_current_weather_to_weather_topic():
    service = make_service_without_llm()

    result = service._force_fresh_web_research(
        message="What's the current weather in Lahore?",
        result={
            "intent": "question",
            "query": None,
            "web_action": None,
            "web_topic": None,
            "web_time_range": None,
            "requires_tool": False,
        },
    )

    assert result["intent"] == "web"
    assert result["web_action"] == "search"
    assert result["web_topic"] == "weather"
    assert result["requires_tool"] is True


def test_force_fresh_web_research_routes_current_sports_scores_to_live_search():
    service = make_service_without_llm()
    messages = (
        (
            "Aaj Pakistan vs England ka match ho raha hai, kya score chal raha?",
            "Pakistan vs England cricket live score today",
        ),
        (
            "What is the score in Pak vs Eng right now?",
            "Pakistan vs England cricket live score today",
        ),
        (
            "Who is playing in the cricket match right now?",
            "Who is playing in the cricket match right now?",
        ),
        (
            "Show me the latest football score today",
            "Show me the latest football score today",
        ),
    )

    for message, expected_query in messages:
        result = service._force_fresh_web_research(
            message=message,
            result={
                "intent": "question",
                "query": None,
                "web_action": None,
                "web_topic": None,
                "web_time_range": None,
                "requires_tool": False,
            },
        )

        assert result["intent"] == "web"
        assert result["web_action"] == "search"
        assert result["web_topic"] == "general"
        assert result["web_time_range"] == "day"
        assert result["query"] == expected_query
        assert result["requires_tool"] is True


def test_analyze_routes_task_list_requests_deterministically_without_llm():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "Clear task-list requests must not depend on the LLM provider."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )

    messages = (
        "Show my current task list",
        "List my tasks",
        "Show all tasks",
        "What tasks do I have?",
        "What are my available tasks?",
        "What are my pending tasks?",
        "What are the pending tasks?",
        "What are my outstanding tasks?",
        "Mere saare tasks ki list dikhao",
        "Mere tasks dikhao",
        "Mere kaun se task pending pade hain?",
        "Mere kaun se pending tasks hain?",
        "Mere kaun se tasks remaining hain?",
        "Mere paas kaun se tasks pending hain?",
        "Mujhe batao mere kaun se task pending hain",
        "Meri task list dikhao",
        "Task list dikhao",
        "List all of my tasks.",
        "List pending tasks to find Nova test a basic",
        "\u092e\u0947\u0930\u0947 \u0938\u093e\u0930\u0947 \u091f\u093e\u0938\u094d\u0915 \u0932\u093f\u0938\u094d\u091f \u0915\u0930\u094b\u0964",
        "\u092e\u0947\u0930\u0947 \u0938\u093e\u0930\u0947 \u091f\u093e\u0938\u094d\u0915 \u0915\u0940 \u0938\u0942\u091a\u0940 \u0926\u093f\u0916\u093e\u0913\u0964",
        "\u0915\u094d\u092f\u093e \u092e\u0947\u0930\u0947 \u0915\u094b\u0908 \u091f\u093e\u0938\u094d\u0915 \u0939\u0948\u0902?",
        "\u092e\u0947\u0930\u0947 \u092a\u093e\u0938 \u0915\u094c\u0928-\u0915\u094c\u0928 \u0938\u0947 \u091f\u093e\u0938\u094d\u0915 \u0939\u0948\u0902?"
    )

    for message in messages:
        result = service.analyze(
            message=message,
            history=[],
        )

        assert result["intent"] == "task", message
        assert result["task_action"] == "list", message
        assert result["task"] is None, message
        assert result["task_reference"] is None, message
        assert result["task_id"] is None, message
        assert result["requires_tool"] is True, message
        assert "llm_provider_unavailable" not in result, message



def test_desktop_website_open_beats_misheard_wake_word_app_search():
    messages = (
        "Nava Wikipedia open karna",
        "Vedika Wikipedia open karna",
        "Indova Wikipedia open karo",
        "Nova Wikipedia open karo",
        "Wikipedia open karo",
    )

    for message in messages:
        result = IntentService._deterministic_desktop_fallback(message)
        assert result is not None, message
        assert result["intent"] == "desktop", message
        assert result["desktop_operation"] == "open_url", message
        assert result["desktop_target"] == "https://www.wikipedia.org", message
        assert result["requires_tool"] is True, message


def test_analyze_routes_roman_urdu_and_hindi_calendar_lists_without_llm():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "Clear calendar-list requests must not depend on the LLM provider."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )

    messages = (
        "Mere kal ke calendar event dikhao. Abhi koi event create ya edit mat karna.",
        "Mere calendar events dikhao",
        "मेरे कल के कैलेंडर इवेंट दिखाओ। अभी कोई इवेंट क्रिएट या एडिट मत करना।",
        "Show my calendar events for tomorrow",
    )

    for message in messages:
        result = service.analyze(message=message, history=[])
        assert result["intent"] == "calendar", message
        assert result["calendar_action"] == "list", message
        assert result["requires_tool"] is True, message

    for message in (messages[0], messages[2], messages[3]):
        result = service.analyze(message=message, history=[])
        assert result["time_min"], message
        assert result["time_max"], message


def test_analyze_routes_bulk_task_deletion_deterministically_without_llm():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "Clear bulk task deletion must not depend on the LLM provider."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )

    expected = {
        "Delete all my pending tasks.": "pending",
        "Delete every task": None,
        "Delete all of my tasks": None,
        "Saare pending tasks delete kar do": "pending",
        "Delete all my tasks, please": None,
    }

    for message, expected_status in expected.items():
        result = service.analyze(message=message, history=[])

        assert result["intent"] == "task", message
        assert result["task_action"] == "delete", message
        assert result["bulk_task_delete"] is True, message
        assert result["task_status_filter"] == expected_status, message
        assert result["task_id"] is None, message
        assert result["task_reference"] is None, message
        assert result["requires_tool"] is True, message
        assert "llm_provider_unavailable" not in result, message


def test_analyze_routes_reminder_list_requests_deterministically_without_llm():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "Clear reminder-list requests must not depend on the LLM provider."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )

    messages = (
        "What are my current reminders?",
        "What are my reminders?",
        "List all of my reminders.",
        "Show my pending reminders",
    )

    for message in messages:
        result = service.analyze(
            message=message,
            history=[],
        )

        assert result["intent"] == "reminder", message
        assert result["reminder_action"] == "list", message
        assert result["requires_tool"] is True, message
        assert "llm_provider_unavailable" not in result, message


def test_analyze_resolves_new_named_task_with_default_priority_and_no_due_date():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "Clear named task creation must not depend on the LLM provider."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )

    messages = (
        "Create a new task named Nova Test A Basic with no due date and default priority.",
        "Create task named Nova Test A Basic with no due date and default priority.",
    )
    for message in messages:
        result = service.analyze(message=message, history=[])

        assert result["intent"] == "task", message
        assert result["task_action"] == "create", message
        assert result["task"] == "Nova Test A Basic", message
        assert result["priority"] is None, message
        assert result["scheduled_at"] is None, message
        assert result["requires_tool"] is True, message
        assert "llm_provider_unavailable" not in result, message



def test_analyze_extracts_quoted_task_title_from_title_introducer():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "Clear task titles must be extracted without an LLM call."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )

    cases = (
        (
            'Create a task with the title "NOVA TEST Run 20261018 A Basic".',
            "NOVA TEST Run 20261018 A Basic",
        ),
        (
            'Create a task with the exact title "NOVA TEST C Cancel Me". '
            "Leave due date empty and use default priority.",
            "NOVA TEST C Cancel Me",
        ),
        (
            "Nova ek task create karo jiska exact title "
            "'NOVA TEST Exact Roman Title 20261018 Z9' ho. "
            "Due date mat rakhna aur default priority use karna.",
            "NOVA TEST Exact Roman Title 20261018 Z9",
        ),
        (
            "Nova ek task create karo jiska exact title "
            "NOVA TEST Unquoted Roman Title 20261018 Z11 ho. "
            "Due date mat rakhna aur default priority use karna.",
            "NOVA TEST Unquoted Roman Title 20261018 Z11",
        ),
        (
            "Create a task with the exact title NOVA TEST Unquoted English 20261018 Z12, "
            "no due date and default priority.",
            "NOVA TEST Unquoted English 20261018 Z12",
        ),
    )

    for message, expected_title in cases:
        result = service.analyze(message=message, history=[])

        assert result["intent"] == "task", message
        assert result["task_action"] == "create", message
        assert result["task"] == expected_title, message
        assert result["priority"] is None, message
        assert result["scheduled_at"] is None, message
        assert result["requires_tool"] is True, message
        assert "llm_provider_unavailable" not in result, message

    quote = chr(39)
    single_quoted_message = (
        "Create a task with the exact title "
        + quote
        + "Nova Test Retest 2026 10 18"
        + quote
        + ", no due date, and default priority."
    )
    result = service.analyze(
        message=single_quoted_message,
        history=[],
    )
    assert result["intent"] == "task"
    assert result["task_action"] == "create"
    assert result["task"] == "Nova Test Retest 2026 10 18"
    assert result["priority"] is None
    assert result["scheduled_at"] is None
    assert result["requires_tool"] is True


def test_analyze_routes_numeric_task_priority_update_deterministically():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "An explicit task ID and priority update must not depend on the LLM provider."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )

    result = service.analyze(
        message="Update the priority of task 217 to low.",
        history=[],
    )

    assert result["intent"] == "task"
    assert result["task_action"] == "update"
    assert result["task_id"] == 217
    assert result["priority"] == "low"
    assert result["scheduled_at"] is None
    assert result["requires_tool"] is True
    assert "llm_provider_unavailable" not in result



def test_analyze_extracts_explicit_task_due_datetime_in_pakistan_timezone():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "A clear task with an explicit date and time must not depend on the LLM provider."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )

    result = service.analyze(
        message=(
            'Create a task named "Nova test B" with high priority and set '
            'the due date to October 19, 2026, at 7 PM Pakistan time.'
        ),
        history=[],
    )

    assert result["intent"] == "task"
    assert result["task_action"] == "create"
    assert result["task"] == "Nova test B"
    assert result["priority"] == "high"
    assert result["scheduled_at"] == "2026-10-19T19:00+05:00"
    assert result["requires_tool"] is True
    assert "llm_provider_unavailable" not in result


def test_deterministic_desktop_command_opens_an_allowlisted_application():
    service = make_service_without_llm()

    result = service._deterministic_fallback(
        message="Open Notepad",
        history=[],
    )

    assert result["intent"] == "desktop"
    assert result["action"] == "start"
    assert result["desktop_operation"] == "open_app"
    assert result["desktop_target"] == "notepad"
    assert result["requires_tool"] is True


def test_deterministic_desktop_command_routes_other_installed_apps_by_name():
    service = make_service_without_llm()

    for message in ("Launch Spotify", "Open Visual Studio Code", "Start Spotify app"):
        result = service._deterministic_fallback(message=message, history=[])

        assert result["intent"] == "desktop", message
        assert result["action"] == "start", message
        assert result["desktop_operation"] == "open_app", message
        assert result["desktop_target"] in {"spotify", "visual studio code"}, message
        assert result["requires_tool"] is True, message


def test_deterministic_desktop_command_preserves_exact_url():
    service = make_service_without_llm()

    result = service._deterministic_fallback(
        message="Open https://example.com/path?q=nova",
        history=[],
    )

    assert result["intent"] == "desktop"
    assert result["desktop_operation"] == "open_url"
    assert result["desktop_target"] == "https://example.com/path?q=nova"


def test_deterministic_desktop_command_supports_roman_urdu():
    service = make_service_without_llm()

    result = service._deterministic_fallback(
        message="calculator kholo",
        history=[],
    )

    assert result["intent"] == "desktop"
    assert result["desktop_operation"] == "open_app"
    assert result["desktop_target"] == "calculator"


def test_deterministic_desktop_command_supports_mixed_devanagari_website_with_hai():
    service = make_service_without_llm()

    messages = (
        "Acha, Wikipedia \u0913\u092a\u0928 \u0915\u0930\u0928\u093e \u0939\u0948\u0964",
        "\u0905\u091a\u094d\u091b\u093e, Wikipedia \u0913\u092a\u0928 \u0915\u0930\u0928\u093e \u0939\u0948\u0964",
    )

    for message in messages:
        result = service._deterministic_fallback(message=message, history=[])

        assert result["intent"] == "desktop", message
        assert result["action"] == "start", message
        assert result["desktop_operation"] == "open_url", message
        assert result["desktop_target"] == "https://www.wikipedia.org", message
        assert result["requires_tool"] is True, message


def test_deterministic_desktop_command_supports_mixed_devanagari_notepad():
    service = make_service_without_llm()

    messages = (
        "\u0905\u091a\u094d\u091b\u093e, \u0928\u094b\u091f\u092a\u0948\u0921 "
        "\u0913\u092a\u0928 \u0915\u0930\u0928\u093e\u0964",
        "\u0939\u093e\u0902, Notepad \u0913\u092a\u0928 "
        "\u0915\u0930 \u0926\u094b\u0964",
    )

    for message in messages:
        result = service._deterministic_fallback(message=message, history=[])

        assert result["intent"] == "desktop", message
        assert result["action"] == "start", message
        assert result["desktop_operation"] == "open_app", message
        assert result["desktop_target"] == "notepad", message
        assert result["requires_tool"] is True, message


def test_deterministic_desktop_command_understands_spoken_text_editor_request():
    service = make_service_without_llm()

    result = service._deterministic_fallback(
        message=(
            "Abhi to nikaal do mere liye text editor. "
            "Notepad, browser aur aise dusre launch kar sakti hun."
        ),
        history=[],
    )

    assert result["intent"] == "desktop"
    assert result["action"] == "start"
    assert result["desktop_operation"] == "open_app"
    assert result["desktop_target"] == "text editor"
    assert result["requires_tool"] is True


def test_deterministic_desktop_command_opens_google_tab_before_missing_query():
    service = make_service_without_llm()

    result = service._deterministic_fallback(
        message="Acha ek tab open karna Google tab, wahan pe search karo",
        history=[],
    )

    assert result["intent"] == "desktop"
    assert result["action"] == "start"
    assert result["desktop_operation"] == "open_url"
    assert result["desktop_target"] == "https://www.google.com"
    assert result["requires_tool"] is True


def test_deterministic_desktop_file_search_keeps_query_and_uses_search_action():
    service = make_service_without_llm()

    result = service._deterministic_fallback(
        message="Search my files for NOVA roadmap",
        history=[],
    )

    assert result["intent"] == "desktop"
    assert result["action"] == "search"
    assert result["desktop_operation"] == "find_files"
    assert result["desktop_query"] == "NOVA roadmap"
    assert result["requires_tool"] is True


def test_deterministic_voice_commands_route_cv_drive_powerpoint_and_reverse_file_phrases():
    service = make_service_without_llm()
    cases = (
        (
            "Find and list my CV files on my device.",
            "search",
            "find_files",
            "cv",
        ),
        (
            "Achha meri CV dekho wo mujhe batao kaun kaun si hai?",
            "search",
            "find_files",
            "cv",
        ),
        (
            "Open Local Disk C",
            "start",
            "open_folder",
            "local disk c",
        ),
        (
            "Open Local Drive C",
            "start",
            "open_folder",
            "local disk c",
        ),
        (
            "Local Drive C open karna",
            "start",
            "open_folder",
            "local disk c",
        ),
        (
            "".join(map(chr, (0x0905, 0x091a, 0x094d, 0x091b, 0x093e, 0x20, 0x0932, 0x094b, 0x0915, 0x0932, 0x20, 0x0921, 0x093f, 0x0938, 0x094d, 0x0915, 0x20, 0x0938, 0x0940, 0x20, 0x0913, 0x092a, 0x0928, 0x20, 0x0915, 0x0930, 0x0928, 0x093e, 0x0964))),
            "start",
            "open_folder",
            "local disk c",
        ),
        (
            "Power PowerPoint open karna.",
            "start",
            "open_app",
            "powerpoint",
        ),
        (
            "Spotify kholo",
            "start",
            "open_app",
            "spotify",
        ),
        (
            "VS Code open karna.",
            "start",
            "open_app",
            "vs code",
        ),
        (
            "World open karna file.",
            "start",
            "open_file",
            "world",
        ),
    )

    for message, expected_action, expected_operation, expected_target in cases:
        result = service._deterministic_fallback(message=message, history=[])
        assert result["intent"] == "desktop", message
        assert result["action"] == expected_action, message
        assert result["desktop_operation"] == expected_operation, message
        actual_target = (
            result.get("desktop_query")
            if expected_operation == "find_files"
            else result.get("desktop_target")
        )
        assert actual_target == expected_target, message
        assert result["requires_tool"] is True, message


def test_devanagari_wikipedia_search_runs_as_a_desktop_action():
    from urllib.parse import quote_plus

    service = make_service_without_llm()
    message = "अच्छा, विकिपीडिया पर कोरियन ड्रामा सर्च करो।"
    result = service._deterministic_fallback(message=message, history=[])

    assert result["intent"] == "desktop"
    assert result["action"] == "start"
    assert result["desktop_operation"] == "open_url"
    assert result["desktop_target"] == (
        "https://en.wikipedia.org/w/index.php?search="
        + quote_plus("कोरियन ड्रामा", safe="")
    )
    assert result["requires_tool"] is True


def test_devanagari_youtube_search_runs_as_a_desktop_action():
    from urllib.parse import quote_plus

    service = make_service_without_llm()
    message = "अच्छा, यूट्यूब पर गाने सर्च करो।"
    result = service._deterministic_fallback(message=message, history=[])

    assert result["intent"] == "desktop"
    assert result["desktop_operation"] == "open_url"
    assert result["desktop_target"] == (
        "https://www.youtube.com/results?search_query="
        + quote_plus("गाने", safe="")
    )


def test_deterministic_youtube_play_requests_require_a_specific_title():
    service = make_service_without_llm()
    cases = (
        ("Play Interstellar soundtrack on YouTube", "Interstellar soundtrack"),
        ("YouTube pe Atif Aslam Tajdar-e-Haram chalao", "Atif Aslam Tajdar-e-Haram"),
        ("YouTube kholo aur Interstellar chalao", "Interstellar"),
        ("YouTube par Kesariya bajao", "Kesariya"),
        ("YouTube mein pal-pal song chalana mere liye", "Pal Pal"),
        ("YouTube par Pal Pal song chalayen", "Pal Pal"),
        ("\u0905\u091a\u094d\u091b\u093e YouTube \u092a\u0930 \u092a\u0932-\u092a\u0932 \u0938\u0949\u0928\u094d\u0917 \u091a\u0932\u093e\u0928\u093e\u0964", "Pal Pal"),
        ("YouTube mein पल-पल सॉन्ग चलाना मेरे लिए।", "Pal Pal"),
        ("YouTube par MrBeast ki koi latest video chalao", "MrBeast ki koi latest video"),
        ("अच्छा, यूट्यूब पर दिल दीयां गल्लां चलाओ।", "दिल दीयां गल्लां"),
        ("YouTube खोलो और इंटरस्टेलर साउंडट्रैक चलाओ।", "Interstellar soundtrack"),
    )

    for message, expected_title in cases:
        result = service._deterministic_fallback(message=message, history=[])
        assert result["intent"] == "desktop", message
        assert result["action"] == "start", message
        assert result["desktop_operation"] == "play_youtube", message
        assert result["desktop_target"] == expected_title, message
        assert result["requires_tool"] is True, message

    for message in (
        "YouTube kholo aur koi song chala do",
        "Play any song on YouTube",
        "YouTube par gaana chalao",
    ):
        result = service._deterministic_fallback(message=message, history=[])
        assert not result or result.get("desktop_operation") != "play_youtube", message
        assert not result or result.get("requires_tool") is not True, message


def test_deterministic_ui_actions_route_to_bounded_desktop_operations():
    service = make_service_without_llm()
    cases = (
        ("What's open on my screen?", "inspect_screen", None, None),
        ("What's on my screen right now?", "inspect_screen", None, None),
        ("What open on my screen right now?", "inspect_screen", None, None),
        ("Inspect the desktop", "inspect_screen", None, None),
        ("Screen pe kya hai", "inspect_screen", None, None),
        ("Meri screen dikhao", "inspect_screen", None, None),
        ("मेरे स्क्रीन पर अभी क्या ओपन है?", "inspect_screen", None, None),
        ("स्क्रीन दिखाओ", "inspect_screen", None, None),
        ("डेस्कटॉप पर क्या दिख रहा है", "inspect_screen", None, None),
        ("Click Search in YouTube", "click_ui", "search", "youtube"),
        ("Tap Play in YouTube", "click_ui", "play", "youtube"),
        ("Type Interstellar into Search", "type_ui", "search", "interstellar"),
        ("Press CTRL+L in Opera", "press_key", "ctrl+l", "opera"),
        ("Search button pe click kar do", "click_ui", "search", None),
        ("YouTube mein Search button pe click kar do", "click_ui", "search", "youtube"),
        ("Search bar mein Interstellar likh do", "type_ui", "search bar", "interstellar"),
        ("CTRL+L dabao", "press_key", "ctrl+l", None),
    )

    for message, operation, target, query in cases:
        result = service._deterministic_fallback(message=message, history=[])
        assert result["intent"] == "desktop", message
        assert result["action"] == "start", message
        assert result["desktop_operation"] == operation, message
        assert result.get("desktop_target") == target, message
        assert result.get("desktop_query") == query, message
        assert result["requires_tool"] is True, message


def test_deterministic_desktop_routes_screen_downloads_recycle_bin_and_music_commands():
    service = make_service_without_llm()
    cases = (
        ("What is on my screen?", "start", "inspect_screen", None, None),
        ("What's on my screen?", "start", "inspect_screen", None, None),
        ("What’s open on my screen?", "start", "inspect_screen", None, None),
        ("Meri downloaded files dikhao", "search", "list_files", None, "downloads"),
        ("Downloads dikhao", "search", "list_files", None, "downloads"),
        ("List files in Downloads", "search", "list_files", None, "downloads"),
        ("Spotify kholo aur Pal Pal chalao", "start", "play_spotify", "Pal Pal", None),
        ("Recycle Bin open karo", "start", "open_folder", "recycle bin", None),
        ("Cycle bin open karo", "start", "open_folder", "recycle bin", None),
        ("This PC open karo", "start", "open_folder", "this pc", None),
        ("Open This PC", "start", "open_folder", "this pc", None),
        ("Open Microsoft Store.", "start", "open_app", "microsoft store", None),
        ("Microsoft Store open karo", "start", "open_app", "microsoft store", None),
        ("Windows Store kholo", "start", "open_app", "microsoft store", None),
        ("Spotify par jao aur Pal Pal song chalao", "start", "play_spotify", "Pal Pal", None),
        ("Spotify पर जाओ और पल पल सॉन्ग चलाओ।", "start", "play_spotify", "Pal Pal", None),
        ("MrBeast ki latest video chalao", "start", "play_youtube", "mrbeast latest video", None),
        ("MrBeast ne jo like latest video upload ki hai na usko chalao", "start", "play_youtube", "mrbeast latest video", None),
        ("YouTube par jao aur MrBeast ki latest video chalao", "start", "play_youtube", "MrBeast ki latest video", None),
        ("YouTube खोलो और इंटरस्टेलर साउंडट्रैक चलाओ।", "start", "play_youtube", "Interstellar soundtrack", None),
    )

    for message, action, operation, target, query in cases:
        result = service._deterministic_fallback(message=message, history=[])
        assert result["intent"] == "desktop", message
        assert result["action"] == action, message
        assert result["desktop_operation"] == operation, message
        assert result.get("desktop_target") == target, message
        assert result.get("desktop_query") == query, message
        assert result["requires_tool"] is True, message


def test_deterministic_browser_search_phrasings_route_to_real_search_urls():
    service = make_service_without_llm()
    cases = (
        (
            "Search for artificial intelligence on Google.",
            "search_web",
            "artificial intelligence",
        ),
        (
            "Google pe search karo movies",
            "search_web",
            "movies",
        ),
        (
            "Search Wikipedia for movies",
            "open_url",
            "https://en.wikipedia.org/w/index.php?search=movies",
        ),
        (
            "Search on Wikipedia for NOVA",
            "open_url",
            "https://en.wikipedia.org/w/index.php?search=NOVA",
        ),
        (
            "Search on YouTube for NOVA voice",
            "open_url",
            "https://www.youtube.com/results?search_query=NOVA+voice",
        ),
        (
            "Movies ko Google pe search karo",
            "search_web",
            "Movies",
        ),
        (
            "Wikipedia par ja kar udhar jo search bar hai, wahan par search karo movies",
            "open_url",
            "https://en.wikipedia.org/w/index.php?search=movies",
        ),
        (
            "Wikipedia par jakar udhar jo search bar hai, wahan movie search karo.",
            "open_url",
            "https://en.wikipedia.org/w/index.php?search=movie",
        ),
        (
            "Wikipedia par ja kar wahan search bar mein movies search karo",
            "open_url",
            "https://en.wikipedia.org/w/index.php?search=movies",
        ),
        (
            "Wikipedia \u092a\u0930 \u091c\u093e\u0915\u0930 \u0935\u0939\u093e\u0902 \u0938\u0930\u094d\u091a \u092c\u093e\u0930 \u092e\u0947\u0902 \u092e\u0942\u0935\u0940 \u0938\u0930\u094d\u091a \u0915\u0930\u094b\u0964",
            "open_url",
            "https://en.wikipedia.org/w/index.php?search=movie",
        ),
        (
            "Google par jao aur Pakistan versus Sri Lanka likho.",
            "search_web",
            "Pakistan versus Sri Lanka",
        ),
        (
            "YouTube par Interstellar search karo.",
            "open_url",
            "https://www.youtube.com/results?search_query=Interstellar",
        ),
        (
            "YouTube pe Interstellar search karo",
            "open_url",
            "https://www.youtube.com/results?search_query=Interstellar",
        ),
    )

    for message, expected_operation, expected_target in cases:
        result = service._deterministic_fallback(message=message, history=[])
        assert result["intent"] == "desktop", message
        assert result["action"] == "start", message
        assert result["desktop_operation"] == expected_operation, message
        assert result["desktop_target"] == expected_target, message
        assert result["requires_tool"] is True, message

def test_relative_devanagari_search_followup_uses_recent_explicit_website_context():
    service = make_service_without_llm()

    result = service._deterministic_fallback(
        message="तुम खुद जाकर वहां पर सर्च करो ना मूवीज।",
        history=[
            {
                "role": "user",
                "content": "Wikipedia par jakar udhar jo search bar hai, wahan movie search karo.",
            }
        ],
    )

    assert result["intent"] == "desktop"
    assert result["desktop_operation"] == "open_url"
    assert result["desktop_target"] == "https://en.wikipedia.org/w/index.php?search=movies"
    assert result["requires_tool"] is True


def test_vague_google_search_request_does_not_execute_a_placeholder_query():
    service = make_service_without_llm()

    result = service._deterministic_fallback(
        message="Google search mein kuch search karo",
        history=[],
    )

    assert result["intent"] != "desktop"
    assert result.get("requires_tool") is not True

def test_validate_desktop_operation_fails_closed_for_unknown_operations():
    service = make_service_without_llm()

    validated = service._validate_result({
        "intent": "desktop",
        "action": "start",
        "desktop_operation": "run_shell",
        "desktop_target": "powershell",
        "requires_tool": True,
    })

    assert validated["intent"] == "chat"
    assert validated["requires_tool"] is False
    assert validated["desktop_operation"] is None


def test_validate_desktop_file_search_rejects_path_traversal():
    service = make_service_without_llm()

    validated = service._validate_result({
        "intent": "desktop",
        "action": "search",
        "desktop_operation": "find_files",
        "desktop_query": r"..\\secret",
        "requires_tool": True,
    })

    assert validated["intent"] == "chat"
    assert validated["requires_tool"] is False
    assert validated["desktop_query"] is None



def test_deterministic_desktop_command_opens_bare_safe_filename():
    service = make_service_without_llm()

    result = service._deterministic_fallback(
        message="Open proposal.pdf",
        history=[],
    )

    assert result["intent"] == "desktop"
    assert result["desktop_operation"] == "open_file"
    assert result["desktop_target"] == "proposal.pdf"



def test_voice_desktop_command_opens_named_wikipedia_after_spoken_filler():
    service = make_service_without_llm()

    result = service._deterministic_fallback(
        message="Okay, open Wikimedia. Wikipedia",
        history=[],
    )

    assert result["intent"] == "desktop"
    assert result["action"] == "start"
    assert result["desktop_operation"] == "open_url"
    assert result["desktop_target"] == "https://www.wikipedia.org"
    assert result["requires_tool"] is True

def test_voice_desktop_command_opens_wikipedia_after_smalltalk_prefix():
    service = make_service_without_llm()

    result = service._deterministic_fallback(
        message="I'm doing great. Wikipedia open karo.",
        history=[],
    )

    assert result["intent"] == "desktop"
    assert result["action"] == "start"
    assert result["desktop_operation"] == "open_url"
    assert result["desktop_target"] == "https://www.wikipedia.org"
    assert result["requires_tool"] is True


def test_voice_desktop_command_opens_wikipedia_for_mixed_devanagari_transcript():
    service = make_service_without_llm()
    result = service._deterministic_fallback(
        message="\u0905\u091a\u094d\u091b\u093e, Wikipedia \u0913\u092a\u0928 \u0915\u0930\u0928\u093e\u0964",
        history=[],
    )
    assert result["intent"] == "desktop"
    assert result["action"] == "start"
    assert result["desktop_operation"] == "open_url"
    assert result["desktop_target"] == "https://www.wikipedia.org"
    assert result["requires_tool"] is True


def test_voice_desktop_command_opens_notepad_when_user_phrase_has_a_capability_tail():
    service = make_service_without_llm()
    result = service._deterministic_fallback(
        message="Acha open Notepad to open kar sakte ho na?",
        history=[],
    )
    assert result["intent"] == "desktop"
    assert result["desktop_operation"] == "open_app"
    assert result["desktop_target"] == "notepad"
    assert result["requires_tool"] is True


def test_voice_desktop_command_opens_wikipedia_with_open_kar_lo_preface():
    service = make_service_without_llm()

    result = service._deterministic_fallback(
        message="Acha Wikipedia open kar lo.",
        history=[],
    )

    assert result["intent"] == "desktop"
    assert result["action"] == "start"
    assert result["desktop_operation"] == "open_url"
    assert result["desktop_target"] == "https://www.wikipedia.org"
    assert result["requires_tool"] is True


def test_voice_desktop_command_opens_notepad_with_open_kar_lo_preface():
    service = make_service_without_llm()

    result = service._deterministic_fallback(
        message="Acha Notepad open kar lo.",
        history=[],
    )

    assert result["intent"] == "desktop"
    assert result["action"] == "start"
    assert result["desktop_operation"] == "open_app"
    assert result["desktop_target"] == "notepad"
    assert result["requires_tool"] is True


def test_voice_desktop_command_ignores_restatement_preface():
    service = make_service_without_llm()

    result = service._deterministic_fallback(
        message="I said open Wikipedia.",
        history=[],
    )

    assert result["intent"] == "desktop"
    assert result["desktop_operation"] == "open_url"
    assert result["desktop_target"] == "https://www.wikipedia.org"


def test_roman_urdu_task_visibility_question_routes_to_persisted_task_list():
    service = make_service_without_llm()

    for message in (
        "Ab dekho kya task mein nazar aa raha hai?",
        "Show me my tasks",
        "What tasks do I have?",
    ):
        result = service.analyze(message=message, history=[])

        assert result["intent"] == "task", message
        assert result["task_action"] == "list", message
        assert result["requires_tool"] is True, message
        assert result["clarification_required"] is False, message


def test_explicit_hindi_task_title_routes_to_task_creation_deterministically():
    service = make_service_without_llm()
    message = (
        "\u0939\u093e\u0902, \u0907\u0938\u0915\u094b "
        "\u0915\u094d\u0930\u093f\u090f\u091f \u0915\u0930 \u0926\u094b\u0964 "
        "\u091f\u093e\u0907\u091f\u0932 \u092a\u0924\u093e \u0939\u0948 \u0915\u094d\u092f\u093e \u0939\u0948? "
        "\u091f\u093e\u0907\u091f\u0932 \u0939\u0948 Nova Live Title Check 2338, "
        "\u0913\u0915\u0947?"
    )

    result = service.analyze(message=message, history=[])

    assert result["intent"] == "task"
    assert result["task_action"] == "create"
    assert result["task"] == "Nova Live Title Check 2338"
    assert result["requires_tool"] is True
    assert result["clarification_required"] is False


def test_affirmative_task_creation_confirmation_preserves_exact_user_title():
    service = make_service_without_llm()

    history = [
        {
            "role": "user",
            "content": (
                "हां, इसको क्रिएट कर दो। टाइटल पता है क्या है? "
                "टाइटल है Nova Live Title Check 2338, ओके?"
            ),
        },
        {
            "role": "assistant",
            "content": (
                "I will add a task titled Nova Live Title Check 2338. "
                "Let me know if that is exactly what you want, and I will create it right now."
            ),
        },
    ]

    result = service.analyze(
        message="Okay, okay. Yes, this is what I want.",
        history=history,
    )

    assert result is not None
    assert result["intent"] == "task"
    assert result["task_action"] == "create"
    assert result["task"] == "Nova Live Title Check 2338"
    assert result["requires_tool"] is True
    assert result["clarification_required"] is False


def test_task_creation_confirmation_does_not_fire_without_explicit_title():
    service = make_service_without_llm()

    history = [
        {
            "role": "user",
            "content": "Create a task for me.",
        },
        {
            "role": "assistant",
            "content": (
                "I can create a task. Let me know if that is exactly what you want, "
                "and I will create it right now."
            ),
        },
    ]

    assert service._resolve_task_creation_confirmation(
        message="Yes, this is what I want.",
        history=history,
    ) is None

def test_voice_wikipedia_asr_aliases_route_to_website_deterministically():
    service = make_service_without_llm()
    messages = (
        "Nava Wikipedia open karna",
        "Vedika Wikipedia open karna",
        "Indova Wikipedia open karo",
        "Nova Wikipedia open karo",
        "Dova Wikipedia open karna",
        "Wikipedia open karo",
    )

    for message in messages:
        result = service._deterministic_fallback(
            message=message,
            history=[],
        )
        assert result["intent"] == "desktop", message
        assert result["desktop_operation"] == "open_url", message
        assert result["desktop_target"] == "https://www.wikipedia.org", message


def test_analyze_routes_structured_test_email_without_llm():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "A complete structured send-email request must be parsed deterministically."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=UnexpectedLLMCall()
        )
    )

    message = (
        "Send a test email to sarosh548548@gmail.com.\n\n"
        "Subject: NOVA Live Email Test 2026-10-21\n\n"
        "Body: This is a test email from NOVA to verify Gmail integration and delivery."
    )
    result = service.analyze(message=message, history=[])

    assert result["intent"] == "email"
    assert result["email_action"] == "send"
    assert result["action"] == "send"
    assert result["to"] == "sarosh548548@gmail.com"
    assert result["recipient_reference"] is None
    assert result["subject"] == "NOVA Live Email Test 2026-10-21"
    assert result["body"] == (
        "This is a test email from NOVA to verify Gmail integration and delivery."
    )
    assert result["requires_tool"] is True
    assert "llm_provider_unavailable" not in result


def test_analyze_routes_composed_voice_email_to_confirmation_pipeline_without_llm():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError(
                "A composed explicit send-email request must be parsed deterministically."
            )

    service.client = SimpleNamespace(
        chat=SimpleNamespace(completions=UnexpectedLLMCall())
    )

    message = (
        "Send an email to saroshqais1@gmail.com with the subject "
        "'Nova Voice Email Retest' and the body "
        "'This is a fresh voice test to verify email delivery.'"
    )
    result = service.analyze(message=message, history=[])

    assert result["intent"] == "email"
    assert result["email_action"] == "send"
    assert result["action"] == "send"
    assert result["to"] == "saroshqais1@gmail.com"
    assert result["subject"] == "Nova Voice Email Retest"
    assert result["body"] == "This is a fresh voice test to verify email delivery."
    assert result["requires_tool"] is True
    assert "llm_provider_unavailable" not in result

def test_composed_voice_email_prefers_recent_explicitly_corrected_recipient():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError("Composed email should be parsed deterministically.")

    service.client = SimpleNamespace(
        chat=SimpleNamespace(completions=UnexpectedLLMCall())
    )
    history = [
        {"role": "user", "content": "Email address hai saroshqais@gmail.com"},
        {"role": "assistant", "content": "I have noted saroshqais@gmail.com."},
        {"role": "user", "content": "Galat kar rahe ho, saroshqais1@gmail.com"},
        {
            "role": "assistant",
            "content": "Theek hai, saroshqais1@gmail.com. Subject aur body bataiye.",
        },
    ]
    message = (
        "Send an email to surooshqais1@gmail.com with the subject "
        "'Nova Voice Email' and the message "
        "'mera test successful complete ho gaya hai'."
    )
    result = service.analyze(message=message, history=history)

    assert result["intent"] == "email"
    assert result["email_action"] == "send"
    assert result["to"] == "saroshqais1@gmail.com"
    assert result["subject"] == "Nova Voice Email"
    assert result["body"] == "mera test successful complete ho gaya hai"
    assert result["requires_tool"] is True


def test_voice_style_composed_email_without_with_and_with_instruction_routes_deterministically():
    service = make_service_without_llm()

    class UnexpectedLLMCall:
        def create(self, **kwargs):
            raise AssertionError("Voice-composed email must be parsed without the LLM.")

    service.client = SimpleNamespace(
        chat=SimpleNamespace(completions=UnexpectedLLMCall())
    )
    message = (
        "Send an email to saroshqais1@gmail.com subject "
        "Nova voice email retest 2 message this is a fresh voice test after the fix. "
        "Please repeat the recipient address before asking my approval."
    )

    result = service.analyze(message=message, history=[])

    assert result["intent"] == "email"
    assert result["email_action"] == "send"
    assert result["action"] == "send"
    assert result["to"] == "saroshqais1@gmail.com"
    assert result["subject"] == "Nova voice email retest 2"
    assert result["body"] == "this is a fresh voice test after the fix."
    assert result["requires_tool"] is True
