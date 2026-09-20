from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main

from api.auth import (
    AuthenticatedContext,
    get_current_auth_context,
)
from api.permissions import (
    get_permission_service,
)
from models.user import User
from models.user_session import UserSession


def _authenticated_context(
    user_id="user-001",
):
    now = datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )

    user = User(
        id=user_id,
        display_name="Permission API Test",
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    session = UserSession(
        id="permission-api-test-session",
        user_id=user_id,
        refresh_token_hash="p" * 64,
        expires_at=now.replace(
            year=now.year + 1
        ),
        last_used_at=now,
        revoked_at=None,
        created_at=now,
        updated_at=now,
    )

    return AuthenticatedContext(
        user=user,
        session=session,
    )


class FakePermissionService:
    def __init__(self):
        self.permissions = [
            {
                "id": 1,
                "tool": "task",
                "action": "create",
                "mode": "confirm",
                "created_at": datetime(
                    2026,
                    9,
                    20,
                    10,
                    0,
                ),
                "updated_at": datetime(
                    2026,
                    9,
                    20,
                    10,
                    0,
                ),
            }
        ]
        self.list_calls = []
        self.set_calls = []
        self.delete_calls = []
        self.delete_result = True
        self.raise_on_set = None

    def list_permissions(
        self,
        *,
        user_id,
    ):
        self.list_calls.append(
            user_id
        )
        return list(
            self.permissions
        )

    def set_permission(
        self,
        *,
        user_id,
        tool,
        action,
        mode,
    ):
        self.set_calls.append(
            {
                "user_id": user_id,
                "tool": tool,
                "action": action,
                "mode": mode,
            }
        )

        if self.raise_on_set is not None:
            raise self.raise_on_set

        normalized_tool = tool.strip().lower()
        normalized_action = action.strip().lower()

        for permission in self.permissions:
            if (
                permission["tool"]
                == normalized_tool
                and permission["action"]
                == normalized_action
            ):
                permission["mode"] = mode
                return True

        self.permissions.append(
            {
                "id": 2,
                "tool": normalized_tool,
                "action": normalized_action,
                "mode": mode,
                "created_at": datetime(
                    2026,
                    9,
                    20,
                    11,
                    0,
                ),
                "updated_at": datetime(
                    2026,
                    9,
                    20,
                    11,
                    0,
                ),
            }
        )
        return True

    def delete_permission(
        self,
        *,
        user_id,
        tool,
        action,
    ):
        self.delete_calls.append(
            {
                "user_id": user_id,
                "tool": tool,
                "action": action,
            }
        )
        return self.delete_result


@pytest.fixture
def authenticated_client():
    service = FakePermissionService()

    main.app.dependency_overrides[
        get_current_auth_context
    ] = lambda: _authenticated_context()

    main.app.dependency_overrides[
        get_permission_service
    ] = lambda: service

    client = TestClient(
        main.app
    )

    try:
        yield client, service

    finally:
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )
        main.app.dependency_overrides.pop(
            get_permission_service,
            None,
        )


def test_permissions_require_authentication():
    client = TestClient(
        main.app
    )

    response = client.get(
        "/permissions"
    )

    assert response.status_code == 401


def test_list_permissions_uses_authenticated_user(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.get(
        "/permissions"
    )

    assert response.status_code == 200
    assert response.json()[0]["tool"] == "task"
    assert response.json()[0]["mode"] == "confirm"
    assert service.list_calls == [
        "user-001"
    ]


def test_set_permission_uses_authenticated_user(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.put(
        "/permissions/task/create",
        json={
            "mode": "allow"
        },
    )

    assert response.status_code == 200
    assert response.json()["tool"] == "task"
    assert response.json()["action"] == "create"
    assert response.json()["mode"] == "allow"
    assert service.set_calls == [
        {
            "user_id": "user-001",
            "tool": "task",
            "action": "create",
            "mode": "allow",
        }
    ]


def test_set_permission_rejects_unknown_action(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.put(
        "/permissions/task/not-an-action",
        json={
            "mode": "allow"
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Unknown permission action."
    )
    assert service.set_calls == []


def test_set_permission_rejects_invalid_mode(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.put(
        "/permissions/task/create",
        json={
            "mode": "maybe"
        },
    )

    assert response.status_code == 422
    assert service.set_calls == []


def test_set_permission_maps_service_error(
    authenticated_client,
):
    client, service = authenticated_client
    service.raise_on_set = ValueError(
        "Tool name is missing."
    )

    response = client.put(
        "/permissions/task/create",
        json={
            "mode": "allow"
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Tool name is missing."
    )


def test_delete_permission_uses_authenticated_user(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.delete(
        "/permissions/task/create"
    )

    assert response.status_code == 204
    assert service.delete_calls == [
        {
            "user_id": "user-001",
            "tool": "task",
            "action": "create",
        }
    ]


def test_delete_missing_permission_returns_404(
    authenticated_client,
):
    client, service = authenticated_client
    service.delete_result = False

    response = client.delete(
        "/permissions/task/create"
    )

    assert response.status_code == 404


def test_user_identity_cannot_be_overridden(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.get(
        "/permissions",
        params={
            "user_id": "attacker-user"
        },
    )

    assert response.status_code == 200
    assert service.list_calls == [
        "user-001"
    ]
