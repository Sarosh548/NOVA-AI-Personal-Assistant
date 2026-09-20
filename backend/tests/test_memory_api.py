from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main

from api.auth import (
    AuthenticatedContext,
    get_current_auth_context,
)
from api.memories import (
    get_memory_service,
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
        display_name="Memory API Test",
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    session = UserSession(
        id="memory-api-test-session",
        user_id=user_id,
        refresh_token_hash="m" * 64,
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


class FakeMemoryService:
    def __init__(self):
        self.memory = {
            "id": 7,
            "memory": "User prefers Python.",
            "category": "preference",
            "importance": "medium",
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
        self.list_calls = []
        self.search_calls = []
        self.get_calls = []
        self.update_calls = []
        self.delete_calls = []
        self.get_result = self.memory
        self.update_result = True
        self.delete_result = True
        self.raise_on_update = None

    def list_memories(
        self,
        *,
        user_id,
        category,
        importance,
        limit,
    ):
        self.list_calls.append(
            {
                "user_id": user_id,
                "category": category,
                "importance": importance,
                "limit": limit,
            }
        )
        return [self.memory]

    def find_similar_memories(
        self,
        *,
        user_id,
        new_memory,
        threshold,
        limit,
    ):
        self.search_calls.append(
            {
                "user_id": user_id,
                "new_memory": new_memory,
                "threshold": threshold,
                "limit": limit,
            }
        )
        return [
            {
                "id": 7,
                "memory": "User prefers Python.",
                "category": "preference",
                "importance": "medium",
                "similarity": 0.91,
                "ranking_score": 0.93,
            }
        ]

    def get_memory(
        self,
        *,
        user_id,
        memory_id,
    ):
        self.get_calls.append(
            {
                "user_id": user_id,
                "memory_id": memory_id,
            }
        )
        return self.get_result

    def update_memory(
        self,
        *,
        user_id,
        memory_id,
        memory_text,
        category,
        importance,
    ):
        self.update_calls.append(
            {
                "user_id": user_id,
                "memory_id": memory_id,
                "memory_text": memory_text,
                "category": category,
                "importance": importance,
            }
        )

        if self.raise_on_update is not None:
            raise self.raise_on_update

        return self.update_result

    def delete_memory(
        self,
        *,
        user_id,
        memory_id,
    ):
        self.delete_calls.append(
            {
                "user_id": user_id,
                "memory_id": memory_id,
            }
        )
        return self.delete_result


@pytest.fixture
def authenticated_client():
    service = FakeMemoryService()

    main.app.dependency_overrides[
        get_current_auth_context
    ] = lambda: _authenticated_context()

    main.app.dependency_overrides[
        get_memory_service
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
            get_memory_service,
            None,
        )


def test_memories_require_authentication():
    client = TestClient(
        main.app
    )

    response = client.get(
        "/memories"
    )

    assert response.status_code == 401


def test_list_memories_uses_authenticated_user(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.get(
        "/memories",
        params={
            "category": "preference",
            "importance": "medium",
            "limit": 20,
        },
    )

    assert response.status_code == 200
    assert response.json()[0]["memory"] == (
        "User prefers Python."
    )
    assert service.list_calls == [
        {
            "user_id": "user-001",
            "category": "preference",
            "importance": "medium",
            "limit": 20,
        }
    ]


def test_search_memories_uses_authenticated_user(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.get(
        "/memories/search",
        params={
            "query": "Python projects",
            "threshold": 0.7,
            "limit": 5,
        },
    )

    assert response.status_code == 200
    assert response.json()[0]["similarity"] == 0.91
    assert service.search_calls == [
        {
            "user_id": "user-001",
            "new_memory": "Python projects",
            "threshold": 0.7,
            "limit": 5,
        }
    ]


def test_get_memory_uses_authenticated_user(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.get(
        "/memories/7"
    )

    assert response.status_code == 200
    assert response.json()["id"] == 7
    assert service.get_calls == [
        {
            "user_id": "user-001",
            "memory_id": 7,
        }
    ]


def test_get_missing_memory_returns_404(
    authenticated_client,
):
    client, service = authenticated_client
    service.get_result = None

    response = client.get(
        "/memories/7"
    )

    assert response.status_code == 404


def test_update_memory_uses_authenticated_user(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.patch(
        "/memories/7",
        json={
            "memory": "User prefers Python for AI development.",
            "category": "preference",
            "importance": "high",
        },
    )

    assert response.status_code == 200
    assert response.json()["memory"] == (
        "User prefers Python for AI development."
        if False
        else "User prefers Python."
    )
    assert service.update_calls == [
        {
            "user_id": "user-001",
            "memory_id": 7,
            "memory_text": (
                "User prefers Python for AI development."
            ),
            "category": "preference",
            "importance": "high",
        }
    ]
    assert service.get_calls == [
        {
            "user_id": "user-001",
            "memory_id": 7,
        }
    ]


def test_update_missing_memory_returns_404(
    authenticated_client,
):
    client, service = authenticated_client
    service.update_result = False

    response = client.patch(
        "/memories/7",
        json={
            "memory": "Updated memory",
        },
    )

    assert response.status_code == 404
    assert service.get_calls == []


def test_update_invalid_payload_returns_422(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.patch(
        "/memories/7",
        json={
            "memory": "",
        },
    )

    assert response.status_code == 422
    assert service.update_calls == []


def test_update_service_value_error_returns_400(
    authenticated_client,
):
    client, service = authenticated_client
    service.raise_on_update = ValueError(
        "Memory text cannot be empty."
    )

    response = client.patch(
        "/memories/7",
        json={
            "memory": "Updated memory",
        },
    )

    assert response.status_code == 400


def test_delete_memory_uses_authenticated_user(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.delete(
        "/memories/7"
    )

    assert response.status_code == 204
    assert service.delete_calls == [
        {
            "user_id": "user-001",
            "memory_id": 7,
        }
    ]


def test_delete_missing_memory_returns_404(
    authenticated_client,
):
    client, service = authenticated_client
    service.delete_result = False

    response = client.delete(
        "/memories/7"
    )

    assert response.status_code == 404


def test_user_identity_cannot_be_overridden(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.get(
        "/memories",
        params={
            "user_id": "attacker-user",
        },
    )

    assert response.status_code == 200
    assert service.list_calls[0]["user_id"] == (
        "user-001"
    )
