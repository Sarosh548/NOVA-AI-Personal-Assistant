from datetime import datetime

from fastapi.testclient import TestClient

import main
from api.auth import get_current_auth_context
from api.conversations import (
    get_conversation_service,
)


class FakeConversationService:
    def __init__(self):
        self.created = []
        self.list_calls = []
        self.history_calls = []
        self.state_calls = []
        self.update_calls = []
        self.delete_calls = []

    def create_conversation(
        self,
        *,
        user_id,
        title,
    ):
        self.created.append(
            {
                "user_id": user_id,
                "title": title,
            }
        )

        return 101

    def get_conversations(
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

        return [
            {
                "id": 101,
                "title": "Project NOVA",
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
                "id": 100,
                "title": "Old Conversation",
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

    def get_history(
        self,
        *,
        user_id,
        conversation_id,
        limit,
    ):
        self.history_calls.append(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "limit": limit,
            }
        )

        return [
            {
                "role": "user",
                "content": "Hello NOVA",
            },
            {
                "role": "assistant",
                "content": "Hello! How can I help?",
            },
        ]

    def get_conversation_state(
        self,
        *,
        user_id,
        conversation_id,
    ):
        self.state_calls.append(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
            }
        )

        return {
            "state": "awaiting_user",
            "last_role": "assistant",
            "should_listen": True,
        }

    def update_conversation_title(
        self,
        *,
        conversation_id,
        user_id,
        title,
    ):
        self.update_calls.append(
            {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "title": title,
            }
        )

        return True

    def delete_conversation(
        self,
        *,
        user_id,
        conversation_id,
    ):
        self.delete_calls.append(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
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


def test_conversation_endpoints_require_authentication():
    main.app.dependency_overrides.pop(
        get_current_auth_context,
        None,
    )

    client = TestClient(
        main.app
    )

    response = client.get(
        "/conversations"
    )

    assert response.status_code == 401


def test_create_conversation_uses_authenticated_identity(
    monkeypatch,
):
    service = FakeConversationService()

    monkeypatch.setattr(
        main,
        "conversation_service",
        main.conversation_service,
    )

    main.app.dependency_overrides[
        get_conversation_service
    ] = lambda: service

    main.app.dependency_overrides[
        get_current_auth_context
    ] = _authenticated_context

    client = TestClient(
        main.app
    )

    try:
        response = client.post(
            "/conversations",
            json={
                "title": "My NOVA Chat",
            },
        )

        assert response.status_code == 201
        assert response.json() == {
            "id": 101
        }

        assert service.created == [
            {
                "user_id": "user-001",
                "title": "My NOVA Chat",
            }
        ]

    finally:
        main.app.dependency_overrides.pop(
            get_conversation_service,
            None,
        )
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )


def test_get_conversations_uses_authenticated_identity():
    service = FakeConversationService()

    main.app.dependency_overrides[
        get_conversation_service
    ] = lambda: service

    main.app.dependency_overrides[
        get_current_auth_context
    ] = _authenticated_context

    client = TestClient(
        main.app
    )

    try:
        response = client.get(
            "/conversations?limit=10"
        )

        assert response.status_code == 200

        assert response.json() == [
            {
                "id": 101,
                "title": "Project NOVA",
                "created_at": (
                    "2026-09-19T08:00:00"
                ),
                "updated_at": (
                    "2026-09-19T08:30:00"
                ),
            },
            {
                "id": 100,
                "title": "Old Conversation",
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
                "limit": 10,
            }
        ]

    finally:
        main.app.dependency_overrides.pop(
            get_conversation_service,
            None,
        )
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )


def test_get_conversation_messages_uses_authenticated_identity():
    service = FakeConversationService()

    main.app.dependency_overrides[
        get_conversation_service
    ] = lambda: service

    main.app.dependency_overrides[
        get_current_auth_context
    ] = _authenticated_context

    client = TestClient(
        main.app
    )

    try:
        response = client.get(
            "/conversations/101/messages?limit=20"
        )

        assert response.status_code == 200

        assert response.json() == {
            "conversation_id": 101,
            "messages": [
                {
                    "role": "user",
                    "content": "Hello NOVA",
                },
                {
                    "role": "assistant",
                    "content": (
                        "Hello! How can I help?"
                    ),
                },
            ],
        }

        assert service.history_calls == [
            {
                "user_id": "user-001",
                "conversation_id": 101,
                "limit": 20,
            }
        ]

    finally:
        main.app.dependency_overrides.pop(
            get_conversation_service,
            None,
        )
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )


def test_get_conversation_state_uses_authenticated_identity():
    service = FakeConversationService()

    main.app.dependency_overrides[
        get_conversation_service
    ] = lambda: service

    main.app.dependency_overrides[
        get_current_auth_context
    ] = _authenticated_context

    client = TestClient(
        main.app
    )

    try:
        response = client.get(
            "/conversations/101/state"
        )

        assert response.status_code == 200

        assert response.json() == {
            "conversation_id": 101,
            "state": "awaiting_user",
            "last_role": "assistant",
            "should_listen": True,
        }

        assert service.state_calls == [
            {
                "user_id": "user-001",
                "conversation_id": 101,
            }
        ]

    finally:
        main.app.dependency_overrides.pop(
            get_conversation_service,
            None,
        )
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )


def test_update_conversation_uses_authenticated_identity():
    service = FakeConversationService()

    main.app.dependency_overrides[
        get_conversation_service
    ] = lambda: service

    main.app.dependency_overrides[
        get_current_auth_context
    ] = _authenticated_context

    client = TestClient(
        main.app
    )

    try:
        response = client.patch(
            "/conversations/101",
            json={
                "title": "Renamed NOVA Chat",
            },
        )

        assert response.status_code == 200

        assert response.json() == {
            "updated": True
        }

        assert service.update_calls == [
            {
                "conversation_id": 101,
                "user_id": "user-001",
                "title": "Renamed NOVA Chat",
            }
        ]

    finally:
        main.app.dependency_overrides.pop(
            get_conversation_service,
            None,
        )
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )


def test_delete_conversation_uses_authenticated_identity():
    service = FakeConversationService()

    main.app.dependency_overrides[
        get_conversation_service
    ] = lambda: service

    main.app.dependency_overrides[
        get_current_auth_context
    ] = _authenticated_context

    client = TestClient(
        main.app
    )

    try:
        response = client.delete(
            "/conversations/101"
        )

        assert response.status_code == 204
        assert response.content == b""

        assert service.delete_calls == [
            {
                "user_id": "user-001",
                "conversation_id": 101,
            }
        ]

    finally:
        main.app.dependency_overrides.pop(
            get_conversation_service,
            None,
        )
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )


def test_update_missing_conversation_returns_404():
    class MissingConversationService(
        FakeConversationService
    ):
        def update_conversation_title(
            self,
            *,
            conversation_id,
            user_id,
            title,
        ):
            return False

    service = MissingConversationService()

    main.app.dependency_overrides[
        get_conversation_service
    ] = lambda: service

    main.app.dependency_overrides[
        get_current_auth_context
    ] = _authenticated_context

    client = TestClient(
        main.app
    )

    try:
        response = client.patch(
            "/conversations/999",
            json={
                "title": "Missing",
            },
        )

        assert response.status_code == 404

        assert response.json() == {
            "detail": "Conversation not found."
        }

    finally:
        main.app.dependency_overrides.pop(
            get_conversation_service,
            None,
        )
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )


def test_delete_missing_conversation_returns_404():
    class MissingConversationService(
        FakeConversationService
    ):
        def delete_conversation(
            self,
            *,
            user_id,
            conversation_id,
        ):
            return False

    service = MissingConversationService()

    main.app.dependency_overrides[
        get_conversation_service
    ] = lambda: service

    main.app.dependency_overrides[
        get_current_auth_context
    ] = _authenticated_context

    client = TestClient(
        main.app
    )

    try:
        response = client.delete(
            "/conversations/999"
        )

        assert response.status_code == 404

        assert response.json() == {
            "detail": "Conversation not found."
        }

    finally:
        main.app.dependency_overrides.pop(
            get_conversation_service,
            None,
        )
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )