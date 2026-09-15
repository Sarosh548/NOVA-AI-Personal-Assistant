from services.intent_service import IntentService


def make_service_without_llm():
    service = IntentService.__new__(IntentService)
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