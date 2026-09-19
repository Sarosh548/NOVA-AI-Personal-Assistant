from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import main
from api.auth import get_current_auth_context
from api.confirmations import (
    get_confirmation_execution_service,
    get_confirmation_service,
)
from services.confirmation_execution_service import (
    ConfirmationExecutionResult,
)


class FakeConfirmationService:
    def __init__(
        self,
        confirmations=None,
        confirmation=None,
        approved=None,
        rejected=None,
    ):
        self.confirmations = (
            confirmations
            if confirmations is not None
            else []
        )

        self.confirmation = confirmation

        self.approved = (
            approved
            if approved is not None
            else confirmation
        )

        self.rejected = (
            rejected
            if rejected is not None
            else confirmation
        )

        self.list_calls = []
        self.get_calls = []
        self.approve_calls = []
        self.reject_calls = []

    def list_pending_confirmations(
        self,
        *,
        user_id,
        conversation_id,
    ):
        self.list_calls.append(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
            }
        )

        return list(
            self.confirmations
        )

    def get_confirmation(
        self,
        *,
        user_id,
        confirmation_id,
    ):
        self.get_calls.append(
            {
                "user_id": user_id,
                "confirmation_id": confirmation_id,
            }
        )

        if self.confirmation is None:
            return None

        if self.confirmation["id"] != confirmation_id:
            return None

        return dict(
            self.confirmation
        )

    def approve_confirmation(
        self,
        *,
        user_id,
        confirmation_id,
    ):
        self.approve_calls.append(
            {
                "user_id": user_id,
                "confirmation_id": confirmation_id,
            }
        )

        if self.approved is None:
            return None

        return dict(
            self.approved
        )

    def reject_confirmation(
        self,
        *,
        user_id,
        confirmation_id,
    ):
        self.reject_calls.append(
            {
                "user_id": user_id,
                "confirmation_id": confirmation_id,
            }
        )

        if self.rejected is None:
            return None

        return dict(
            self.rejected
        )


class FakeConfirmationExecutionService:
    def __init__(
        self,
        result=None,
    ):
        self.result = result or (
            _execution_result()
        )

        self.calls = []
        self.approve_and_execute_calls = []

    def execute_approved_confirmation(
        self,
        *,
        user_id,
        confirmation_id,
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "confirmation_id": confirmation_id,
            }
        )

        return self.result

    def approve_and_execute_confirmation(
        self,
        *,
        user_id,
        confirmation_id,
    ):
        self.approve_and_execute_calls.append(
            {
                "user_id": user_id,
                "confirmation_id": confirmation_id,
            }
        )

        return self.result


def _authenticated_context():
    from types import SimpleNamespace

    return SimpleNamespace(
        user=SimpleNamespace(
            id="user-001",
        )
    )


def _sample_confirmation(
    *,
    confirmation_id=101,
    status="pending",
    conversation_id=7,
    resolved_at=None,
):
    return {
        "id": confirmation_id,
        "user_id": "user-001",
        "conversation_id": conversation_id,
        "tool": "email",
        "action": "send",
        "data": {
            "to": "test@example.com",
            "subject": "Test",
        },
        "reason": (
            "Sending this email requires confirmation."
        ),
        "status": status,
        "created_at": datetime(
            2026,
            9,
            19,
            9,
            0,
        ),
        "expires_at": datetime(
            2026,
            9,
            19,
            9,
            5,
        ),
        "resolved_at": resolved_at,
    }


def _execution_result(
    *,
    success=True,
    status="completed",
):
    confirmation_status = (
        "consumed"
        if success
        else "failed"
    )

    confirmation = _sample_confirmation(
        confirmation_id=101,
        status=confirmation_status,
        resolved_at=datetime(
            2026,
            9,
            19,
            9,
            2,
        ),
    )

    return ConfirmationExecutionResult(
        success=success,
        status=status,
        confirmation=confirmation,
        tool_result={
            "success": success,
            "tool": "email",
            "action": "send",
            "result": (
                {
                    "message_id": "msg-1"
                }
                if success
                else None
            ),
            "error": (
                None
                if success
                else "Email failed."
            ),
        },
        workflow_result={
            "success": False,
            "status": None,
            "workflow_id": None,
            "scheduled_at": None,
            "steps": [],
            "error": None,
        },
        error=(
            None
            if success
            else "Email failed."
        ),
    )


@pytest.fixture
def authenticated_api():
    pending = _sample_confirmation(
        confirmation_id=101
    )

    approved = _sample_confirmation(
        confirmation_id=101,
        status="approved",
        resolved_at=datetime(
            2026,
            9,
            19,
            9,
            2,
        ),
    )

    rejected = _sample_confirmation(
        confirmation_id=101,
        status="rejected",
        resolved_at=datetime(
            2026,
            9,
            19,
            9,
            3,
        ),
    )

    confirmation_service = FakeConfirmationService(
        confirmations=[
            pending,
            _sample_confirmation(
                confirmation_id=100,
                conversation_id=6,
            ),
        ],
        confirmation=pending,
        approved=approved,
        rejected=rejected,
    )

    execution_service = (
        FakeConfirmationExecutionService()
    )

    main.app.dependency_overrides[
        get_confirmation_service
    ] = lambda: confirmation_service

    main.app.dependency_overrides[
        get_confirmation_execution_service
    ] = lambda: execution_service

    main.app.dependency_overrides[
        get_current_auth_context
    ] = _authenticated_context

    client = TestClient(
        main.app
    )

    try:
        yield (
            client,
            confirmation_service,
            execution_service,
        )

    finally:
        main.app.dependency_overrides.pop(
            get_confirmation_service,
            None,
        )

        main.app.dependency_overrides.pop(
            get_confirmation_execution_service,
            None,
        )

        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )


def test_confirmation_list_requires_authentication():
    main.app.dependency_overrides.pop(
        get_current_auth_context,
        None,
    )

    client = TestClient(
        main.app
    )

    response = client.get(
        "/confirmations"
    )

    assert response.status_code == 401


def test_get_pending_confirmations_uses_authenticated_identity(
    authenticated_api,
):
    client, service, execution_service = authenticated_api

    response = client.get(
        "/confirmations"
    )

    assert response.status_code == 200

    payload = response.json()

    assert len(payload) == 2
    assert payload[0]["id"] == 101
    assert payload[0]["status"] == "pending"
    assert payload[0]["tool"] == "email"
    assert payload[0]["action"] == "send"

    assert service.list_calls == [
        {
            "user_id": "user-001",
            "conversation_id": None,
        }
    ]


def test_get_pending_confirmations_passes_conversation_filter(
    authenticated_api,
):
    client, service, execution_service = authenticated_api

    response = client.get(
        "/confirmations?conversation_id=7"
    )

    assert response.status_code == 200

    assert service.list_calls == [
        {
            "user_id": "user-001",
            "conversation_id": 7,
        }
    ]


def test_get_pending_confirmations_rejects_invalid_conversation_id(
    authenticated_api,
):
    client, service, execution_service = authenticated_api

    response = client.get(
        "/confirmations?conversation_id=0"
    )

    assert response.status_code == 422


def test_get_confirmation_uses_authenticated_identity(
    authenticated_api,
):
    client, service, execution_service = authenticated_api

    response = client.get(
        "/confirmations/101"
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["id"] == 101
    assert payload["conversation_id"] == 7
    assert payload["tool"] == "email"
    assert payload["action"] == "send"
    assert payload["status"] == "pending"

    assert payload["data"] == {
        "to": "test@example.com",
        "subject": "Test",
    }

    assert service.get_calls == [
        {
            "user_id": "user-001",
            "confirmation_id": 101,
        }
    ]


def test_get_confirmation_returns_not_found(
    authenticated_api,
):
    client, service, execution_service = authenticated_api

    response = client.get(
        "/confirmations/999"
    )

    assert response.status_code == 404

    assert response.json() == {
        "detail": "Confirmation not found."
    }


def test_get_confirmation_preserves_resolved_status(
    authenticated_api,
):
    client, service, execution_service = authenticated_api

    service.confirmation = _sample_confirmation(
        confirmation_id=101,
        status="consumed",
        resolved_at=datetime(
            2026,
            9,
            19,
            9,
            3,
        ),
    )

    response = client.get(
        "/confirmations/101"
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["status"] == "consumed"
    assert payload["resolved_at"] == (
        "2026-09-19T09:03:00"
    )


def test_approve_confirmation_uses_authenticated_identity(
    authenticated_api,
):
    client, service, execution_service = authenticated_api

    response = client.post(
        "/confirmations/101/approve"
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["id"] == 101
    assert payload["status"] == "approved"

    assert service.approve_calls == [
        {
            "user_id": "user-001",
            "confirmation_id": 101,
        }
    ]

    assert execution_service.calls == []


def test_reject_confirmation_uses_authenticated_identity(
    authenticated_api,
):
    client, service, execution_service = authenticated_api

    response = client.post(
        "/confirmations/101/reject"
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["id"] == 101
    assert payload["status"] == "rejected"

    assert service.reject_calls == [
        {
            "user_id": "user-001",
            "confirmation_id": 101,
        }
    ]

    assert execution_service.calls == []


def test_approve_and_execute_confirmation_uses_authenticated_identity(
    authenticated_api,
):
    client, service, execution_service = authenticated_api

    response = client.post(
        "/confirmations/101/approve-and-execute"
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["confirmation"]["id"] == 101
    assert payload["confirmation"]["status"] == "consumed"
    assert payload["success"] is True
    assert payload["status"] == "completed"

    assert payload["tool_result"]["success"] is True

    assert service.approve_calls == []

    assert execution_service.calls == []

    assert execution_service.approve_and_execute_calls == [
        {
            "user_id": "user-001",
            "confirmation_id": 101,
        }
    ]


def test_approve_and_execute_returns_execution_failure(
    authenticated_api,
):
    client, service, execution_service = authenticated_api

    execution_service.result = _execution_result(
        success=False,
        status="failed",
    )

    response = client.post(
        "/confirmations/101/approve-and-execute"
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["confirmation"]["status"] == "failed"
    assert payload["success"] is False
    assert payload["status"] == "failed"
    assert payload["error"] == "Email failed."


def test_approve_and_execute_returns_not_found(
    authenticated_api,
):
    client, service, execution_service = authenticated_api

    service.confirmation = None

    response = client.post(
        "/confirmations/999/approve-and-execute"
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Confirmation not found."
    }

    assert service.approve_calls == []
    assert execution_service.calls == []


def test_approve_and_execute_rejects_non_pending_state(
    authenticated_api,
):
    client, service, execution_service = authenticated_api

    service.confirmation = _sample_confirmation(
        confirmation_id=101,
        status="consumed",
    )

    response = client.post(
        "/confirmations/101/approve-and-execute"
    )

    assert response.status_code == 409

    assert execution_service.calls == []


def test_approve_and_execute_handles_unavailable_confirmation(
    authenticated_api,
):
    client, service, execution_service = authenticated_api

    execution_service.result = ConfirmationExecutionResult(
        success=False,
        status="unavailable",
        confirmation=None,
        tool_result={
            "success": False,
            "tool": None,
            "action": None,
            "result": None,
            "error": "Confirmation was already processed.",
        },
        workflow_result={
            "success": False,
            "status": None,
            "workflow_id": None,
            "scheduled_at": None,
            "steps": [],
            "error": None,
        },
        error="Confirmation was already processed.",
    )

    response = client.post(
        "/confirmations/101/approve-and-execute"
    )

    assert response.status_code == 409

    assert response.json() == {
        "detail": "Confirmation was already processed."
    }