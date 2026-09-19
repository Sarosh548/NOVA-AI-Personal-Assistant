from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import main
from api.auth import get_current_auth_context
from api.workflows import get_workflow_service


class FakeWorkflowService:
    def __init__(
        self,
        workflows=None,
        workflow=None,
        cancelled=None,
    ):
        self.workflows = (
            workflows
            if workflows is not None
            else []
        )

        self.workflow = workflow

        self.cancelled = (
            cancelled
            if cancelled is not None
            else workflow
        )

        self.list_calls = []
        self.get_calls = []
        self.cancel_calls = []

    def list_workflows(
        self,
        *,
        user_id,
        limit,
    ):
        self.list_calls.append(
            {
                "user_id": user_id,
                "limit": limit,
            }
        )

        return list(
            self.workflows
        )

    def get_workflow(
        self,
        *,
        user_id,
        workflow_id,
    ):
        self.get_calls.append(
            {
                "user_id": user_id,
                "workflow_id": workflow_id,
            }
        )

        if self.workflow is None:
            return None

        if self.workflow["id"] != workflow_id:
            return None

        return dict(
            self.workflow
        )

    def cancel_workflow(
        self,
        *,
        user_id,
        workflow_id,
    ):
        self.cancel_calls.append(
            {
                "user_id": user_id,
                "workflow_id": workflow_id,
            }
        )

        if self.cancelled is None:
            return None

        return dict(
            self.cancelled
        )


def _authenticated_context():
    from types import SimpleNamespace

    return SimpleNamespace(
        user=SimpleNamespace(
            id="user-001",
        )
    )


def _sample_step():
    return {
        "id": 11,
        "workflow_id": 101,
        "step_id": "step-1",
        "position": 0,
        "tool": "task",
        "action": "create",
        "data": {
            "task": "Practice NOVA",
        },
        "depends_on": [],
        "status": "pending",
        "result": None,
        "error": None,
        "attempts": 0,
        "created_at": datetime(
            2026,
            9,
            19,
            9,
            0,
        ),
        "updated_at": datetime(
            2026,
            9,
            19,
            9,
            0,
        ),
        "started_at": None,
        "completed_at": None,
    }


def _sample_workflow(
    *,
    workflow_id=101,
    status="pending",
):
    return {
        "id": workflow_id,
        "user_id": "user-001",
        "conversation_id": 7,
        "status": status,
        "execution_mode": "workflow",
        "scheduled_at": None,
        "plan": {
            "execution_mode": "workflow",
            "steps": [
                {
                    "step_id": "step-1",
                    "tool": "task",
                    "action": "create",
                }
            ],
        },
        "result": None,
        "error": None,
        "idempotency_key": None,
        "created_at": datetime(
            2026,
            9,
            19,
            9,
            0,
        ),
        "updated_at": datetime(
            2026,
            9,
            19,
            9,
            0,
        ),
        "started_at": None,
        "completed_at": None,
        "steps": [
            _sample_step()
        ],
    }


@pytest.fixture
def authenticated_api():
    service = FakeWorkflowService(
        workflows=[
            _sample_workflow(
                workflow_id=101
            ),
            _sample_workflow(
                workflow_id=100,
                status="completed",
            ),
        ],
        workflow=_sample_workflow(
            workflow_id=101
        ),
        cancelled=_sample_workflow(
            workflow_id=101,
            status="cancelled",
        ),
    )

    main.app.dependency_overrides[
        get_workflow_service
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
            get_workflow_service,
            None,
        )

        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )


def test_workflow_list_requires_authentication():
    main.app.dependency_overrides.pop(
        get_current_auth_context,
        None,
    )

    client = TestClient(
        main.app
    )

    response = client.get(
        "/workflows"
    )

    assert response.status_code == 401


def test_get_workflows_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.get(
        "/workflows"
    )

    assert response.status_code == 200

    payload = response.json()

    assert len(payload) == 2

    assert payload[0]["id"] == 101
    assert payload[0]["status"] == "pending"
    assert payload[0]["steps"][0]["step_id"] == "step-1"

    assert service.list_calls == [
        {
            "user_id": "user-001",
            "limit": 50,
        }
    ]


def test_get_workflows_passes_limit(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.get(
        "/workflows?limit=20"
    )

    assert response.status_code == 200

    assert service.list_calls == [
        {
            "user_id": "user-001",
            "limit": 20,
        }
    ]


def test_get_workflows_rejects_invalid_limit(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.get(
        "/workflows?limit=0"
    )

    assert response.status_code == 422


def test_get_workflows_rejects_limit_above_maximum(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.get(
        "/workflows?limit=101"
    )

    assert response.status_code == 422


def test_get_workflow_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.get(
        "/workflows/101"
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["id"] == 101
    assert payload["status"] == "pending"
    assert payload["execution_mode"] == "workflow"

    assert service.get_calls == [
        {
            "user_id": "user-001",
            "workflow_id": 101,
        }
    ]


def test_get_workflow_returns_not_found(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.get(
        "/workflows/999"
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Workflow not found."
    }


def test_cancel_workflow_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.post(
        "/workflows/101/cancel"
    )

    assert response.status_code == 200

    assert response.json() == {
        "action": "cancel",
        "updated": True,
    }

    assert service.get_calls == [
        {
            "user_id": "user-001",
            "workflow_id": 101,
        }
    ]

    assert service.cancel_calls == [
        {
            "user_id": "user-001",
            "workflow_id": 101,
        }
    ]


def test_cancel_workflow_returns_not_found(
    authenticated_api,
):
    client, service = authenticated_api

    service.workflow = None

    response = client.post(
        "/workflows/999/cancel"
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Workflow not found."
    }


def test_cancel_workflow_rejects_completed_workflow(
    authenticated_api,
):
    client, service = authenticated_api

    service.workflow = _sample_workflow(
        workflow_id=101,
        status="completed",
    )

    response = client.post(
        "/workflows/101/cancel"
    )

    assert response.status_code == 409

    assert response.json() == {
        "detail": (
            "Workflow cannot be cancelled "
            "in its current state."
        )
    }

    assert service.cancel_calls == []


def test_cancel_workflow_handles_service_conflict(
    authenticated_api,
):
    client, service = authenticated_api

    service.cancelled = None

    response = client.post(
        "/workflows/101/cancel"
    )

    assert response.status_code == 409

    assert response.json() == {
        "detail": (
            "Workflow could not be cancelled "
            "in its current state."
        )
    }