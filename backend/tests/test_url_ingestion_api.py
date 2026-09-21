from __future__ import annotations

from datetime import datetime, timezone

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
        display_name="Knowledge URL API Test",
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    session = UserSession(
        id="knowledge-url-api-test-session",
        user_id=user_id,
        refresh_token_hash="u" * 64,
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
        self.create_url_calls = []
        self.result = {
            "id": 12,
            "title": "NOVA Guide",
            "source": "https://example.com/docs",
            "chunk_count": 2,
            "created_at": datetime(
                2026,
                9,
                21,
                10,
                0,
            ),
            "updated_at": datetime(
                2026,
                9,
                21,
                10,
                0,
            ),
        }
        self.raise_on_create_url = None

    def create_document_from_url(
        self,
        *,
        user_id,
        url,
    ):
        self.create_url_calls.append(
            {
                "user_id": user_id,
                "url": url,
            }
        )

        if self.raise_on_create_url is not None:
            raise self.raise_on_create_url

        return self.result


def _client_with_service():
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

    return client, service


def _clear_overrides():
    main.app.dependency_overrides.pop(
        get_current_auth_context,
        None,
    )
    main.app.dependency_overrides.pop(
        get_knowledge_service,
        None,
    )


def test_knowledge_url_requires_authentication():
    client = TestClient(
        main.app
    )

    response = client.post(
        "/knowledge/urls",
        json={
            "url": "https://example.com",
        },
    )

    assert response.status_code == 401


def test_create_document_from_url_uses_authenticated_user():
    client, service = _client_with_service()

    try:
        response = client.post(
            "/knowledge/urls",
            json={
                "url": "https://example.com/docs",
            },
        )
    finally:
        _clear_overrides()

    assert response.status_code == 201
    assert response.json()["id"] == 12
    assert response.json()["title"] == "NOVA Guide"
    assert service.create_url_calls == [
        {
            "user_id": "user-001",
            "url": "https://example.com/docs",
        }
    ]


def test_create_document_from_url_rejects_invalid_payload():
    client, service = _client_with_service()

    try:
        response = client.post(
            "/knowledge/urls",
            json={
                "url": "",
            },
        )
    finally:
        _clear_overrides()

    assert response.status_code == 422
    assert service.create_url_calls == []


def test_create_document_from_url_maps_service_error_to_400():
    client, service = _client_with_service()
    service.raise_on_create_url = ValueError(
        "url must use http or https."
    )

    try:
        response = client.post(
            "/knowledge/urls",
            json={
                "url": "ftp://example.com",
            },
        )
    finally:
        _clear_overrides()

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "url must use http or https."
    )


def test_create_document_from_url_rejects_extra_fields():
    client, service = _client_with_service()

    try:
        response = client.post(
            "/knowledge/urls",
            json={
                "url": "https://example.com",
                "user_id": "attacker-user",
            },
        )
    finally:
        _clear_overrides()

    assert response.status_code == 422
    assert service.create_url_calls == []
