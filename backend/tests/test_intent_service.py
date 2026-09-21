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
    assert routed["query"] == "What are today's AI news headlines?"
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

