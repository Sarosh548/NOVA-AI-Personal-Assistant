from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main
from api.auth import get_current_auth_context
from api.tasks import get_task_service


class FakeIdempotencyService:
    def __init__(self):
        self.claims = []
        self.completed = []
        self.failed = []

    def claim_or_replay(
        self,
        *,
        user_id,
        endpoint,
        idempotency_key,
        request_hash,
    ):
        self.claims.append({
            "user_id": user_id,
            "endpoint": endpoint,
            "idempotency_key": idempotency_key,
            "request_hash": request_hash,
        })
        return {
            "status": "claimed",
            "record_id": 1,
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
        self.completed.append({
            "record_id": record_id,
            "claim_token": claim_token,
            "response_status": response_status,
            "response_body": response_body,
        })
        return True

    def fail(
        self,
        *,
        record_id,
        claim_token,
        error,
    ):
        self.failed.append({
            "record_id": record_id,
            "claim_token": claim_token,
            "error": error,
        })
        return True


class FakeTaskService:
    def __init__(self):
        self.created = []
        self.list_calls = []
        self.update_calls = []
        self.start_calls = []
        self.complete_calls = []
        self.cancel_calls = []
        self.delete_calls = []

    def create_task(
        self,
        *,
        user_id,
        title,
        description,
        priority,
        due_at,
    ):
        self.created.append(
            {
                "user_id": user_id,
                "title": title,
                "description": description,
                "priority": priority,
                "due_at": due_at,
            }
        )

        return 201

    def get_tasks(
        self,
        *,
        user_id,
        status,
    ):
        self.list_calls.append(
            {
                "user_id": user_id,
                "status": status,
            }
        )

        if status == "invalid":
            raise ValueError(
                "Invalid task status."
            )

        return [
            {
                "id": 201,
                "title": "Practice LangGraph",
                "description": "Agent graph practice.",
                "status": "pending",
                "priority": "high",
                "due_at": datetime(
                    2026,
                    9,
                    20,
                    12,
                    0,
                ),
                "created_at": datetime(
                    2026,
                    9,
                    19,
                    8,
                    0,
                ),
                "updated_at": datetime(
                    2026,
                    9,
                    19,
                    8,
                    30,
                ),
            },
            {
                "id": 200,
                "title": "Review authentication",
                "description": None,
                "status": "completed",
                "priority": "medium",
                "due_at": None,
                "created_at": datetime(
                    2026,
                    9,
                    18,
                    8,
                    0,
                ),
                "updated_at": datetime(
                    2026,
                    9,
                    18,
                    9,
                    0,
                ),
            },
        ]

    def update_task(
        self,
        *,
        task_id,
        user_id,
        priority,
        due_at,
    ):
        self.update_calls.append(
            {
                "task_id": task_id,
                "user_id": user_id,
                "priority": priority,
                "due_at": due_at,
            }
        )

        return True

    def start_task(
        self,
        *,
        task_id,
        user_id,
    ):
        self.start_calls.append(
            {
                "task_id": task_id,
                "user_id": user_id,
            }
        )

        return True

    def complete_task(
        self,
        *,
        task_id,
        user_id,
    ):
        self.complete_calls.append(
            {
                "task_id": task_id,
                "user_id": user_id,
            }
        )

        return True

    def cancel_task(
        self,
        *,
        task_id,
        user_id,
    ):
        self.cancel_calls.append(
            {
                "task_id": task_id,
                "user_id": user_id,
            }
        )

        return True

    def delete_task(
        self,
        *,
        task_id,
        user_id,
    ):
        self.delete_calls.append(
            {
                "task_id": task_id,
                "user_id": user_id,
            }
        )

        return True


def _authenticated_context():
    from types import SimpleNamespace

    return SimpleNamespace(
        user=SimpleNamespace(
            id="user-001",
        )
    )


@pytest.fixture
def authenticated_api():
    service = FakeTaskService()

    main.app.dependency_overrides[
        get_task_service
    ] = lambda: service

    main.app.dependency_overrides[
        get_current_auth_context
    ] = _authenticated_context

    client = TestClient(
        main.app
    )

    try:
        yield client, service

    finally:
        main.app.dependency_overrides.pop(
            get_task_service,
            None,
        )
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )


def test_task_endpoints_require_authentication():
    main.app.dependency_overrides.pop(
        get_current_auth_context,
        None,
    )

    client = TestClient(
        main.app
    )

    response = client.get(
        "/tasks"
    )

    assert response.status_code == 401


def test_create_task_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    due_at = (
        "2026-09-20T12:00:00+00:00"
    )

    response = client.post(
        "/tasks",
        json={
            "title": "Practice LangGraph",
            "description": "Agent graph practice.",
            "priority": "high",
            "due_at": due_at,
            "user_id": "attacker-user",
        },
    )

    assert response.status_code == 201

    assert response.json() == {
        "id": 201
    }

    assert service.created == [
        {
            "user_id": "user-001",
            "title": "Practice LangGraph",
            "description": (
                "Agent graph practice."
            ),
            "priority": "high",
            "due_at": datetime(
                2026,
                9,
                20,
                12,
                0,
                tzinfo=timezone.utc,
            ),
        }
    ]


def test_create_task_value_error_returns_400(
    authenticated_api,
):
    client, service = authenticated_api

    class RejectingTaskService(
        FakeTaskService
    ):
        def create_task(
            self,
            *,
            user_id,
            title,
            description,
            priority,
            due_at,
        ):
            raise ValueError(
                "Invalid task priority."
            )

    rejecting_service = (
        RejectingTaskService()
    )

    main.app.dependency_overrides[
        get_task_service
    ] = lambda: rejecting_service

    response = client.post(
        "/tasks",
        json={
            "title": "Test task",
            "priority": "urgent",
        },
    )

    assert response.status_code == 400

    assert response.json() == {
        "detail": "Invalid task priority."
    }


def test_get_tasks_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.get(
        "/tasks?status=pending"
    )

    assert response.status_code == 200

    assert response.json() == [
        {
            "id": 201,
            "title": "Practice LangGraph",
            "description": (
                "Agent graph practice."
            ),
            "status": "pending",
            "priority": "high",
            "due_at": (
                "2026-09-20T12:00:00"
            ),
            "created_at": (
                "2026-09-19T08:00:00"
            ),
            "updated_at": (
                "2026-09-19T08:30:00"
            ),
        },
        {
            "id": 200,
            "title": "Review authentication",
            "description": None,
            "status": "completed",
            "priority": "medium",
            "due_at": None,
            "created_at": (
                "2026-09-18T08:00:00"
            ),
            "updated_at": (
                "2026-09-18T09:00:00"
            ),
        },
    ]

    assert service.list_calls == [
        {
            "user_id": "user-001",
            "status": "pending",
        }
    ]


def test_get_tasks_invalid_status_returns_400(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.get(
        "/tasks?status=invalid"
    )

    assert response.status_code == 400

    assert response.json() == {
        "detail": "Invalid task status."
    }


def test_update_task_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.patch(
        "/tasks/201",
        json={
            "priority": "high",
            "due_at": (
                "2026-09-21T14:00:00+00:00"
            ),
        },
    )

    assert response.status_code == 200

    assert response.json() == {
        "updated": True
    }

    assert service.update_calls == [
        {
            "task_id": 201,
            "user_id": "user-001",
            "priority": "high",
            "due_at": datetime(
                2026,
                9,
                21,
                14,
                0,
                tzinfo=timezone.utc,
            ),
        }
    ]


def test_update_task_missing_returns_404(
    authenticated_api,
):
    class MissingTaskService(
        FakeTaskService
    ):
        def update_task(
            self,
            *,
            task_id,
            user_id,
            priority,
            due_at,
        ):
            return False

    service = MissingTaskService()

    main.app.dependency_overrides[
        get_task_service
    ] = lambda: service

    client, _ = authenticated_api

    response = client.patch(
        "/tasks/999",
        json={
            "priority": "high",
        },
    )

    assert response.status_code == 404

    assert response.json() == {
        "detail": "Task not found."
    }


def test_start_task_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.post(
        "/tasks/201/start"
    )

    assert response.status_code == 200

    assert response.json() == {
        "action": "start",
        "updated": True,
    }

    assert service.start_calls == [
        {
            "task_id": 201,
            "user_id": "user-001",
        }
    ]


def test_complete_task_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.post(
        "/tasks/201/complete"
    )

    assert response.status_code == 200

    assert response.json() == {
        "action": "complete",
        "updated": True,
    }

    assert service.complete_calls == [
        {
            "task_id": 201,
            "user_id": "user-001",
        }
    ]


def test_cancel_task_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.post(
        "/tasks/201/cancel"
    )

    assert response.status_code == 200

    assert response.json() == {
        "action": "cancel",
        "updated": True,
    }

    assert service.cancel_calls == [
        {
            "task_id": 201,
            "user_id": "user-001",
        }
    ]


def test_delete_task_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.delete(
        "/tasks/201"
    )

    assert response.status_code == 204
    assert response.content == b""

    assert service.delete_calls == [
        {
            "task_id": 201,
            "user_id": "user-001",
        }
    ]


def test_delete_missing_task_returns_404(
    authenticated_api,
):
    class MissingTaskService(
        FakeTaskService
    ):
        def delete_task(
            self,
            *,
            task_id,
            user_id,
        ):
            return False

    service = MissingTaskService()

    main.app.dependency_overrides[
        get_task_service
    ] = lambda: service

    client, _ = authenticated_api

    response = client.delete(
        "/tasks/999"
    )

    assert response.status_code == 404

    assert response.json() == {
        "detail": "Task not found."
    }

def test_create_task_idempotency_key_is_persisted(
    authenticated_api,
    monkeypatch,
):
    client, service = authenticated_api
    import api.tasks as task_module

    fake_idempotency = FakeIdempotencyService()
    monkeypatch.setattr(
        task_module,
        "idempotency_service",
        fake_idempotency,
    )

    response = client.post(
        "/tasks",
        headers={"Idempotency-Key": "task-create-1"},
        json={
            "title": "Practice LangGraph",
            "priority": "high",
        },
    )

    assert response.status_code == 201
    assert response.json() == {"id": 201}
    assert len(fake_idempotency.claims) == 1
    assert fake_idempotency.claims[0]["endpoint"] == "/tasks"
    assert fake_idempotency.claims[0]["idempotency_key"] == "task-create-1"
    assert len(fake_idempotency.completed) == 1
    assert fake_idempotency.completed[0]["response_status"] == 201
    assert fake_idempotency.completed[0]["response_body"] == {"id": 201}


def test_create_task_idempotency_replay_does_not_create_again(
    authenticated_api,
    monkeypatch,
):
    client, service = authenticated_api
    import api.tasks as task_module

    class ReplayService(FakeIdempotencyService):
        def claim_or_replay(self, **kwargs):
            return {
                "status": "replay",
                "record_id": 1,
                "response_body": {"id": 777},
            }

    monkeypatch.setattr(
        task_module,
        "idempotency_service",
        ReplayService(),
    )

    response = client.post(
        "/tasks",
        headers={"Idempotency-Key": "task-create-replay"},
        json={"title": "Repeated task"},
    )

    assert response.status_code == 201
    assert response.json() == {"id": 777}
    assert service.created == []


def test_create_task_idempotency_conflict_returns_409(
    authenticated_api,
    monkeypatch,
):
    client, service = authenticated_api
    import api.tasks as task_module

    class ConflictService(FakeIdempotencyService):
        def claim_or_replay(self, **kwargs):
            return {"status": "conflict", "record_id": 1}

    monkeypatch.setattr(
        task_module,
        "idempotency_service",
        ConflictService(),
    )

    response = client.post(
        "/tasks",
        headers={"Idempotency-Key": "task-create-conflict"},
        json={"title": "Conflict"},
    )

    assert response.status_code == 409
    assert response.json()["detail"].startswith(
        "Idempotency-Key was already used"
    )
    assert service.created == []
