from datetime import datetime, timedelta

from services.task_service import TaskService


def test_normalize_task_text():
    service = TaskService()

    result = service._normalize_task_text(
        "my LangGraph practice task"
    )

    assert result == {
        "langgraph",
        "practice",
    }


def test_normalize_task_text_ignores_generic_words():
    service = TaskService()

    result = service._normalize_task_text(
        "please complete this task"
    )

    assert result == {
        "complete",
    }


def test_create_task_rejects_empty_title():
    service = TaskService()

    try:
        service.create_task(
            user_id="test-user",
            title="",
        )
        assert False
    except ValueError as exc:
        assert (
            str(exc)
            == "Task title cannot be empty."
        )


def test_create_task_rejects_invalid_priority():
    service = TaskService()

    try:
        service.create_task(
            user_id="test-user",
            title="Test task",
            priority="urgent",
        )
        assert False
    except ValueError as exc:
        assert (
            str(exc)
            == "Invalid task priority."
        )


def test_update_task_requires_a_change():
    service = TaskService()

    try:
        service.update_task(
            task_id=1,
            user_id="test-user",
        )
        assert False
    except ValueError as exc:
        assert (
            str(exc)
            == "No task fields were provided for update."
        )


def test_update_task_rejects_invalid_priority():
    service = TaskService()

    try:
        service.update_task(
            task_id=1,
            user_id="test-user",
            priority="urgent",
        )
        assert False
    except ValueError as exc:
        assert (
            str(exc)
            == "Invalid task priority."
        )


def test_update_task_updates_priority(
    monkeypatch,
):
    service = TaskService()

    fake_task = type(
        "FakeTask",
        (),
        {
            "id": 1,
            "user_id": "test-user",
            "priority": "medium",
            "due_at": None,
            "updated_at": None,
        },
    )()

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(
            self,
            exc_type,
            exc_value,
            traceback,
        ):
            return False

        def scalar(self, statement):
            return fake_task

        def commit(self):
            pass

    import services.task_service as task_service_module

    monkeypatch.setattr(
        task_service_module,
        "Session",
        lambda engine: FakeSession(),
    )

    result = service.update_task(
        task_id=1,
        user_id="test-user",
        priority="high",
    )

    assert result is True
    assert fake_task.priority == "high"


def test_update_task_updates_due_time(
    monkeypatch,
):
    service = TaskService()

    future_time = (
        datetime.utcnow()
        + timedelta(hours=2)
    )

    fake_task = type(
        "FakeTask",
        (),
        {
            "id": 2,
            "user_id": "test-user",
            "priority": "medium",
            "due_at": None,
            "updated_at": None,
        },
    )()

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(
            self,
            exc_type,
            exc_value,
            traceback,
        ):
            return False

        def scalar(self, statement):
            return fake_task

        def commit(self):
            pass

    import services.task_service as task_service_module

    monkeypatch.setattr(
        task_service_module,
        "Session",
        lambda engine: FakeSession(),
    )

    result = service.update_task(
        task_id=2,
        user_id="test-user",
        due_at=future_time,
    )

    assert result is True
    assert fake_task.due_at == future_time


def test_update_task_updates_priority_and_due_time(
    monkeypatch,
):
    service = TaskService()

    future_time = (
        datetime.utcnow()
        + timedelta(hours=3)
    )

    fake_task = type(
        "FakeTask",
        (),
        {
            "id": 3,
            "user_id": "test-user",
            "priority": "low",
            "due_at": None,
            "updated_at": None,
        },
    )()

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(
            self,
            exc_type,
            exc_value,
            traceback,
        ):
            return False

        def scalar(self, statement):
            return fake_task

        def commit(self):
            pass

    import services.task_service as task_service_module

    monkeypatch.setattr(
        task_service_module,
        "Session",
        lambda engine: FakeSession(),
    )

    result = service.update_task(
        task_id=3,
        user_id="test-user",
        priority="high",
        due_at=future_time,
    )

    assert result is True
    assert fake_task.priority == "high"
    assert fake_task.due_at == future_time