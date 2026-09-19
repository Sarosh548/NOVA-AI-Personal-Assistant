from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import main
from api.auth import get_current_auth_context
from api.confirmations import get_confirmation_service


class FakeConfirmationService:
    def __init__(
        self,
        confirmations=None,
        confirmation=None,
    ):
        self.confirmations = (
            confirmations
            if confirmations is not None
            else []
        )

        self.confirmation = confirmation

        self.list_calls = []
        self.get_calls = []

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
        "resolved_at": None,
    }


@pytest.fixture
def authenticated_api():
    service = FakeConfirmationService(
        confirmations=[
            _sample_confirmation(
                confirmation_id=101
            ),
            _sample_confirmation(
                confirmation_id=100,
                conversation_id=6,
            ),
        ],
        confirmation=_sample_confirmation(
            confirmation_id=101
        ),
    )

    main.app.dependency_overrides[
        get_confirmation_service
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
            get_confirmation_service,
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
    client, service = authenticated_api

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
    client, service = authenticated_api

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
    client, service = authenticated_api

    response = client.get(
        "/confirmations?conversation_id=0"
    )

    assert response.status_code == 422


def test_get_confirmation_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

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
    client, service = authenticated_api

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
    client, service = authenticated_api

    service.confirmation = _sample_confirmation(
        confirmation_id=101,
        status="consumed",
    )

    service.confirmation["resolved_at"] = datetime(
        2026,
        9,
        19,
        9,
        3,
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


def test_confirmation_list_returns_only_service_results(
    authenticated_api,
):
    client, service = authenticated_api

    service.confirmations = [
        _sample_confirmation(
            confirmation_id=55
        )
    ]

    response = client.get(
        "/confirmations"
    )

    assert response.status_code == 200
    assert response.json()[0]["id"] == 55