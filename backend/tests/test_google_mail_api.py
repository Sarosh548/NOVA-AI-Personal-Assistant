from __future__ import annotations

from fastapi.testclient import TestClient

import main
from api.auth import get_current_auth_context
from api.google_mail import get_google_mail_oauth_service


def _authenticated_context():
    from types import SimpleNamespace
    return SimpleNamespace(user=SimpleNamespace(id="user-001"))


class FakeGoogleMailService:
    MAX_LIST_RESULTS = 10

    def __init__(self):
        self.list_calls = []
        self.get_calls = []

    def list_messages(self, *, user_id, query=None, max_results=5, include_body=False):
        self.list_calls.append({
            "user_id": user_id,
            "query": query,
            "max_results": max_results,
            "include_body": include_body,
        })
        return {
            "provider": "gmail",
            "query": query or "in:inbox",
            "count": 1,
            "messages": [{"id": "message_123", "subject": "Project update"}],
        }

    def get_message(self, *, user_id, message_id):
        self.get_calls.append({
            "user_id": user_id,
            "message_id": message_id,
        })
        return {
            "provider": "gmail",
            "id": message_id,
            "subject": "Project update",
            "body": "The project is on track.",
        }


def test_list_google_mail_messages_uses_authenticated_user():
    service = FakeGoogleMailService()
    main.app.dependency_overrides[get_google_mail_oauth_service] = lambda: service
    main.app.dependency_overrides[get_current_auth_context] = _authenticated_context
    client = TestClient(main.app)

    try:
        response = client.get("/integrations/google/mail/messages?q=in%3Ainbox&max_results=3")
        assert response.status_code == 200
        assert response.json()["messages"][0]["id"] == "message_123"
        assert service.list_calls == [{
            "user_id": "user-001",
            "query": "in:inbox",
            "max_results": 3,
            "include_body": False,
        }]
    finally:
        main.app.dependency_overrides.pop(get_google_mail_oauth_service, None)
        main.app.dependency_overrides.pop(get_current_auth_context, None)


def test_list_google_mail_messages_can_explicitly_include_bodies_for_summaries():
    service = FakeGoogleMailService()
    main.app.dependency_overrides[get_google_mail_oauth_service] = lambda: service
    main.app.dependency_overrides[get_current_auth_context] = _authenticated_context
    client = TestClient(main.app)

    try:
        response = client.get(
            "/integrations/google/mail/messages?max_results=2&include_body=true"
        )
        assert response.status_code == 200
        assert service.list_calls == [{
            "user_id": "user-001",
            "query": None,
            "max_results": 2,
            "include_body": True,
        }]
    finally:
        main.app.dependency_overrides.pop(get_google_mail_oauth_service, None)
        main.app.dependency_overrides.pop(get_current_auth_context, None)


def test_get_google_mail_message_uses_authenticated_user_and_requested_id():
    service = FakeGoogleMailService()
    main.app.dependency_overrides[get_google_mail_oauth_service] = lambda: service
    main.app.dependency_overrides[get_current_auth_context] = _authenticated_context
    client = TestClient(main.app)

    try:
        response = client.get("/integrations/google/mail/messages/message_123")
        assert response.status_code == 200
        assert response.json()["body"] == "The project is on track."
        assert service.get_calls == [{
            "user_id": "user-001",
            "message_id": "message_123",
        }]
    finally:
        main.app.dependency_overrides.pop(get_google_mail_oauth_service, None)
        main.app.dependency_overrides.pop(get_current_auth_context, None)


def test_list_google_mail_messages_rejects_out_of_range_limits():
    service = FakeGoogleMailService()
    main.app.dependency_overrides[get_google_mail_oauth_service] = lambda: service
    main.app.dependency_overrides[get_current_auth_context] = _authenticated_context
    client = TestClient(main.app)

    try:
        response = client.get("/integrations/google/mail/messages?max_results=11")
        assert response.status_code == 422
        assert service.list_calls == []
    finally:
        main.app.dependency_overrides.pop(get_google_mail_oauth_service, None)
        main.app.dependency_overrides.pop(get_current_auth_context, None)


def test_get_google_mail_message_surfaces_safe_validation_errors():
    class InvalidMessageService(FakeGoogleMailService):
        def get_message(self, *, user_id, message_id):
            raise ValueError("Gmail message ID is invalid.")

    service = InvalidMessageService()
    main.app.dependency_overrides[get_google_mail_oauth_service] = lambda: service
    main.app.dependency_overrides[get_current_auth_context] = _authenticated_context
    client = TestClient(main.app)

    try:
        response = client.get("/integrations/google/mail/messages/message_123")
        assert response.status_code == 400
        assert response.json() == {"detail": "Gmail message ID is invalid."}
    finally:
        main.app.dependency_overrides.pop(get_google_mail_oauth_service, None)
        main.app.dependency_overrides.pop(get_current_auth_context, None)
