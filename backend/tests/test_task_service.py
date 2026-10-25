from datetime import datetime, timedelta, timezone

from services.task_service import TaskService


def test_delete_tasks_deletes_exact_confirmed_ids_atomically(monkeypatch):
    import services.task_service as task_service_module

    service = TaskService()
    fake_tasks = [
        type(
            "FakeTask",
            (),
            {
                "id": 10,
                "user_id": "test-user",
                "title": "Task Ten",
                "status": "pending",
                "priority": "high",
                "due_at": None,
            },
        )(),
        type(
            "FakeTask",
            (),
            {
                "id": 11,
                "user_id": "test-user",
                "title": "Task Eleven",
                "status": "pending",
                "priority": "medium",
                "due_at": None,
            },
        )(),
    ]

    class FakeScalars:
        def all(self):
            return fake_tasks

    class FakeSession:
        def __init__(self):
            self.deleted = []
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def scalars(self, statement):
            return FakeScalars()

        def delete(self, task):
            self.deleted.append(task)

        def commit(self):
            self.committed = True

    session = FakeSession()
    monkeypatch.setattr(
        task_service_module,
        "Session",
        lambda engine: session,
    )

    deleted = service.delete_tasks(
        task_ids=[11, 10],
        user_id="test-user",
        expected_status="pending",
    )

    assert [item["id"] for item in deleted] == [11, 10]
    assert [item["title"] for item in deleted] == ["Task Eleven", "Task Ten"]
    assert [task.id for task in session.deleted] == [11, 10]
    assert session.committed is True


def test_delete_tasks_aborts_without_deleting_if_status_changed(monkeypatch):
    import services.task_service as task_service_module

    service = TaskService()
    fake_task = type(
        "FakeTask",
        (),
        {
            "id": 10,
            "user_id": "test-user",
            "title": "Task Ten",
            "status": "completed",
            "priority": "high",
            "due_at": None,
        },
    )()

    class FakeScalars:
        def all(self):
            return [fake_task]

    class FakeSession:
        def __init__(self):
            self.deleted = []
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def scalars(self, statement):
            return FakeScalars()

        def delete(self, task):
            self.deleted.append(task)

        def commit(self):
            self.committed = True

    session = FakeSession()
    monkeypatch.setattr(
        task_service_module,
        "Session",
        lambda engine: session,
    )

    try:
        service.delete_tasks(
            task_ids=[10],
            user_id="test-user",
            expected_status="pending",
        )
        assert False, "Expected status mismatch to abort the batch."
    except ValueError as exc:
        assert "No tasks were deleted" in str(exc)

    assert session.deleted == []
    assert session.committed is False


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


def test_create_task_rejects_overlong_title_instead_of_silently_truncating():
    service = TaskService()
    try:
        service.create_task(
            user_id="test-user",
            title="x" * 301,
        )
        assert False, "Expected overlong title to be rejected."
    except ValueError as exc:
        assert str(exc) == "Task title cannot exceed 300 characters."


def test_create_task_removes_trailing_due_date_instruction_from_title(monkeypatch):
    import services.task_service as task_service_module

    service = TaskService()

    class FakeSession:
        def __init__(self):
            self.added_task = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def add(self, task):
            self.added_task = task

        def commit(self):
            pass

        def refresh(self, task):
            task.id = 42

    session = FakeSession()
    monkeypatch.setattr(
        task_service_module,
        "Session",
        lambda engine: session,
    )

    task_id = service.create_task(
        user_id="test-user",
        title="Nova Live Test task. 1021 ko due date mat lagana",
    )

    assert task_id == 42
    assert session.added_task.title == "Nova Live Test task. 1021"
    assert session.added_task.due_at is None


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
        datetime.now(timezone.utc).replace(
            tzinfo=None
        )
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
        datetime.now(timezone.utc).replace(
            tzinfo=None
        )
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