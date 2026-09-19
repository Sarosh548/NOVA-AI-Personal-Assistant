from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main
from api.activity import (
    get_activity_event_service,
)
from api.auth import get_current_auth_context


class FakeActivityEventService:
    def __init__(self):
        self.calls = []

    def list_events(
        self,
        *,
        user_id,
        limit,
        event_type,
        source,
        since,
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "limit": limit,
                "event_type": event_type,
                "source": source,
                "since": since,
            }
        )

        return [
            {
                "id": 501,
                "user_id": "user-001",
                "conversation_id": 101,
                "workflow_id": None,
                "event_type": "task_completed",
                "source": "tool_router",
                "status": "success",
                "title": "Task completed: Practice NOVA",
                "summary": (
                    "Task action 'complete' succeeded."
                ),
                "metadata": {
                    "tool": "task",
                    "action": "complete",
                    "entity_id": 201,
                },
                "created_at": datetime(
                    2026,
                    9,
                    19,
                    9,
                    30,
                ),
            },
            {
                "id": 500,
                "user_id": "user-001",
                "conversation_id": None,
                "workflow_id": 44,
                "event_type": "workflow_completed",
                "source": "workflow",
                "status": "success",
                "title": "Workflow completed",
                "summary": (
                    "Autonomous workflow completed."
                ),
                "metadata": {
                    "workflow_id": 44,
                },
                "created_at": datetime(
                    2026,
                    9,
                    19,
                    9,
                    0,
                ),
            },
        ]


def _authenticated_context():
    from types import SimpleNamespace

    return SimpleNamespace(
        user=SimpleNamespace(
            id="user-001",
        )
    )


@pytest.fixture
def authenticated_api():
    service = FakeActivityEventService()

    main.app.dependency_overrides[
        get_activity_event_service
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
            get_activity_event_service,
            None,
        )
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )


def test_activity_endpoint_requires_authentication():
    main.app.dependency_overrides.pop(
        get_current_auth_context,
        None,
    )

    client = TestClient(
        main.app
    )

    response = client.get(
        "/activity"
    )

    assert response.status_code == 401


def test_get_activity_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.get(
        "/activity"
    )

    assert response.status_code == 200

    assert response.json() == [
        {
            "id": 501,
            "conversation_id": 101,
            "workflow_id": None,
            "event_type": "task_completed",
            "source": "tool_router",
            "status": "success",
            "title": (
                "Task completed: Practice NOVA"
            ),
            "summary": (
                "Task action 'complete' succeeded."
            ),
            "metadata": {
                "tool": "task",
                "action": "complete",
                "entity_id": 201,
            },
            "created_at": (
                "2026-09-19T09:30:00"
            ),
        },
        {
            "id": 500,
            "conversation_id": None,
            "workflow_id": 44,
            "event_type": "workflow_completed",
            "source": "workflow",
            "status": "success",
            "title": "Workflow completed",
            "summary": (
                "Autonomous workflow completed."
            ),
            "metadata": {
                "workflow_id": 44,
            },
            "created_at": (
                "2026-09-19T09:00:00"
            ),
        },
    ]

    assert service.calls == [
        {
            "user_id": "user-001",
            "limit": 50,
            "event_type": None,
            "source": None,
            "since": None,
        }
    ]


def test_get_activity_passes_limit_and_filters(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.get(
        "/activity"
        "?limit=20"
        "&event_type=task_completed"
        "&source=tool_router"
        "&since=2026-09-19T08:00:00%2B00:00"
    )

    assert response.status_code == 200

    assert len(
        response.json()
    ) == 2

    assert service.calls == [
        {
            "user_id": "user-001",
            "limit": 20,
            "event_type": "task_completed",
            "source": "tool_router",
            "since": datetime(
                2026,
                9,
                19,
                8,
                0,
                tzinfo=timezone.utc,
            ),
        }
    ]


def test_get_activity_rejects_invalid_limit(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.get(
        "/activity?limit=0"
    )

    assert response.status_code == 422


def test_get_activity_rejects_limit_above_maximum(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.get(
        "/activity?limit=101"
    )

    assert response.status_code == 422


def test_get_activity_rejects_oversized_event_type(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.get(
        "/activity?event_type="
        + ("x" * 51)
    )

    assert response.status_code == 422


def test_get_activity_rejects_invalid_since_datetime(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.get(
        "/activity?since=not-a-datetime"
    )

    assert response.status_code == 422