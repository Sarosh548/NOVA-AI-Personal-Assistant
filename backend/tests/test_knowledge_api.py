from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main

from api.auth import (
    AuthenticatedContext,
    get_current_auth_context,
)
from api.knowledge import (
    get_knowledge_service,
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
        display_name="Knowledge API Test",
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    session = UserSession(
        id="knowledge-api-test-session",
        user_id=user_id,
        refresh_token_hash="k" * 64,
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


class FakeKnowledgeService:
    def __init__(self):
        self.document = {
            "id": 7,
            "title": "Python Guide",
            "source": "manual",
            "content": "Python is useful for AI development.",
            "chunk_count": 1,
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
        self.create_calls = []
        self.list_calls = []
        self.search_calls = []
        self.get_calls = []
        self.delete_calls = []
        self.get_result = self.document
        self.create_result = self.document
        self.delete_result = True
        self.raise_on_create = None

    def create_document(
        self,
        *,
        user_id,
        title,
        content,
        source,
    ):
        self.create_calls.append(
            {
                "user_id": user_id,
                "title": title,
                "content": content,
                "source": source,
            }
        )

        if self.raise_on_create is not None:
            raise self.raise_on_create

        return self.create_result

    def list_documents(
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
        return [self.document]

    def search(
        self,
        *,
        user_id,
        query,
        threshold,
        limit,
    ):
        self.search_calls.append(
            {
                "user_id": user_id,
                "query": query,
                "threshold": threshold,
                "limit": limit,
            }
        )
        return [
            {
                "document_id": 7,
                "title": "Python Guide",
                "source": "manual",
                "chunk_index": 0,
                "content": "Python is useful for AI development.",
                "similarity": 0.91,
            }
        ]

    def get_document(
        self,
        *,
        user_id,
        document_id,
    ):
        self.get_calls.append(
            {
                "user_id": user_id,
                "document_id": document_id,
            }
        )
        return self.get_result

    def delete_document(
        self,
        *,
        user_id,
        document_id,
    ):
        self.delete_calls.append(
            {
                "user_id": user_id,
                "document_id": document_id,
            }
        )
        return self.delete_result


@pytest.fixture
def authenticated_client():
    service = FakeKnowledgeService()

    main.app.dependency_overrides[
        get_current_auth_context
    ] = lambda: _authenticated_context()

    main.app.dependency_overrides[
        get_knowledge_service
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
            get_knowledge_service,
            None,
        )


def test_knowledge_requires_authentication():
    client = TestClient(
        main.app
    )

    response = client.get(
        "/knowledge/documents"
    )

    assert response.status_code == 401


def test_create_document_uses_authenticated_user(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.post(
        "/knowledge/documents",
        json={
            "title": "Python Guide",
            "content": "Python is useful for AI development.",
            "source": "manual",
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == 7
    assert service.create_calls == [
        {
            "user_id": "user-001",
            "title": "Python Guide",
            "content": "Python is useful for AI development.",
            "source": "manual",
        }
    ]


def test_create_invalid_payload_returns_422(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.post(
        "/knowledge/documents",
        json={
            "title": "",
            "content": "",
        },
    )

    assert response.status_code == 422
    assert service.create_calls == []


def test_create_service_value_error_returns_400(
    authenticated_client,
):
    client, service = authenticated_client

    service.raise_on_create = ValueError(
        "A document with identical content already exists."
    )

    response = client.post(
        "/knowledge/documents",
        json={
            "title": "Duplicate",
            "content": "Python",
        },
    )

    assert response.status_code == 400


def test_list_documents_uses_authenticated_user(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.get(
        "/knowledge/documents",
        params={"limit": 20},
    )

    assert response.status_code == 200
    assert response.json()[0]["title"] == (
        "Python Guide"
    )
    assert service.list_calls == [
        {
            "user_id": "user-001",
            "limit": 20,
        }
    ]


def test_search_uses_authenticated_user(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.get(
        "/knowledge/search",
        params={
            "query": "Python AI",
            "threshold": 0.7,
            "limit": 5,
        },
    )

    assert response.status_code == 200
    assert response.json()[0]["similarity"] == 0.91
    assert service.search_calls == [
        {
            "user_id": "user-001",
            "query": "Python AI",
            "threshold": 0.7,
            "limit": 5,
        }
    ]


def test_get_document_uses_authenticated_user(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.get(
        "/knowledge/documents/7"
    )

    assert response.status_code == 200
    assert response.json()["id"] == 7
    assert response.json()["content"] == (
        "Python is useful for AI development."
    )
    assert service.get_calls == [
        {
            "user_id": "user-001",
            "document_id": 7,
        }
    ]


def test_missing_document_returns_404(
    authenticated_client,
):
    client, service = authenticated_client
    service.get_result = None

    response = client.get(
        "/knowledge/documents/7"
    )

    assert response.status_code == 404


def test_delete_document_uses_authenticated_user(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.delete(
        "/knowledge/documents/7"
    )

    assert response.status_code == 204
    assert service.delete_calls == [
        {
            "user_id": "user-001",
            "document_id": 7,
        }
    ]


def test_delete_missing_document_returns_404(
    authenticated_client,
):
    client, service = authenticated_client
    service.delete_result = False

    response = client.delete(
        "/knowledge/documents/7"
    )

    assert response.status_code == 404


def test_user_identity_cannot_be_overridden(
    authenticated_client,
):
    client, service = authenticated_client

    response = client.get(
        "/knowledge/documents",
        params={
            "user_id": "attacker-user",
        },
    )

    assert response.status_code == 200
    assert service.list_calls[0]["user_id"] == (
        "user-001"
    )
