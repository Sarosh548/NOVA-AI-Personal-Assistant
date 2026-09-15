from services.task_service import TaskService


def test_normalize_task_text():
    service = TaskService()

    result = service._normalize_task_text(
        "Start my LangGraph practice task."
    )

    assert result == {
        "start",
        "langgraph",
        "practice",
    }


def test_normalize_task_text_ignores_generic_words():
    service = TaskService()

    result = service._normalize_task_text(
        "my Python study task"
    )

    assert result == {
        "python",
        "study",
    }


def test_create_task_rejects_empty_title():
    service = TaskService()

    try:
        service.create_task(
            user_id="test-user",
            title="   ",
        )
    except ValueError as exc:
        assert str(exc) == "Task title cannot be empty."
    else:
        raise AssertionError(
            "Expected ValueError was not raised."
        )


def test_create_task_rejects_invalid_priority():
    service = TaskService()

    try:
        service.create_task(
            user_id="test-user",
            title="Test task",
            priority="urgent",
        )
    except ValueError as exc:
        assert str(exc) == "Invalid task priority."
    else:
        raise AssertionError(
            "Expected ValueError was not raised."
        )