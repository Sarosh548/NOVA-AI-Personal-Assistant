from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from urllib.parse import parse_qs, urlparse
import base64
from email import message_from_bytes
import json

from cryptography.fernet import Fernet
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from models.email_connection import EmailConnection
from models.oauth_state import OAuthState
from models.user import User
from services.google_mail_oauth_service import GoogleMailOAuthService
from services.token_encryption_service import TokenEncryptionService


def build_runtime():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(bind=engine)
    OAuthState.__table__.create(bind=engine)
    EmailConnection.__table__.create(bind=engine)
    with Session(engine) as session:
        session.add(User(id="user-001", display_name="Test", is_active=True))
        session.commit()
    return engine


def build_service(engine):
    from config import Settings

    settings = Settings(
        auth_jwt_secret_key="a" * 32,
        calendar_google_client_id="client-id",
        calendar_google_client_secret="client-secret",
        calendar_google_redirect_uri="http://localhost:8000/integrations/google/calendar/callback",
        integration_token_encryption_key=Fernet.generate_key().decode("utf-8"),
    )
    return GoogleMailOAuthService(
        engine=engine,
        settings=settings,
        encryption_service=TokenEncryptionService(settings.integration_token_encryption_key),
    )


def teardown_runtime(engine):
    EmailConnection.__table__.drop(bind=engine)
    OAuthState.__table__.drop(bind=engine)
    User.__table__.drop(bind=engine)
    engine.dispose()


def seed_connected_mailbox(engine, service):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(engine) as session:
        session.add(
            EmailConnection(
                user_id="user-001",
                provider="google",
                email_address="owner@example.com",
                encrypted_access_token=service._get_encryption_service().encrypt("access-token"),
                encrypted_refresh_token=service._get_encryption_service().encrypt("refresh-token"),
                token_expires_at=now + timedelta(hours=1),
                scopes=f"{service.SEND_SCOPE} {service.READ_SCOPE}",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def test_build_authorization_url_uses_one_time_user_bound_state_and_send_scope():
    engine = build_runtime()
    try:
        service = build_service(engine)
        url = service.build_authorization_url(user_id="user-001")
        query = parse_qs(urlparse(url).query)
        state = query["state"][0]
        assert query["client_id"] == ["client-id"]
        assert query["redirect_uri"] == [
            "http://localhost:8000/integrations/google/calendar/callback"
        ]
        assert GoogleMailOAuthService.SEND_SCOPE in query["scope"][0].split()
        assert GoogleMailOAuthService.READ_SCOPE in query["scope"][0].split()
        assert "https://www.googleapis.com/auth/userinfo.email" in query["scope"][0].split()
        assert service.is_authorization_state(state) is True
        with Session(engine) as session:
            stored = session.scalar(
                __import__("sqlalchemy").select(OAuthState).where(
                    OAuthState.provider == "google-mail"
                )
            )
            assert stored.user_id == "user-001"
            assert stored.state_hash != state
    finally:
        teardown_runtime(engine)


def test_complete_authorization_encrypts_tokens_and_saves_verified_mailbox(monkeypatch):
    engine = build_runtime()
    try:
        service = build_service(engine)
        url = service.build_authorization_url(user_id="user-001")
        state = parse_qs(urlparse(url).query)["state"][0]
        monkeypatch.setattr(
            service,
            "_post_form",
            lambda endpoint, payload, context: {
                "access_token": "raw-access-token",
                "refresh_token": "raw-refresh-token",
                "expires_in": 3600,
                "scope": "openid https://www.googleapis.com/auth/userinfo.email " + service.SEND_SCOPE,
            },
        )
        monkeypatch.setattr(
            service,
            "_get_user_info",
            lambda access_token: {
                "email": "Owner@Example.com",
                "email_verified": True,
            },
        )
        saved = service.complete_authorization(state=state, code="code")
        assert saved["email"] == "owner@example.com"
        assert "encrypted_access_token" not in saved
        connection = service.get_connection(user_id="user-001")
        assert connection["email"] == "owner@example.com"
        with Session(engine) as session:
            record = session.query(EmailConnection).one()
            assert record.encrypted_access_token != "raw-access-token"
            assert record.encrypted_refresh_token != "raw-refresh-token"
        with pytest.raises(ValueError, match="Invalid or expired"):
            service.complete_authorization(state=state, code="code")
    finally:
        teardown_runtime(engine)


def test_send_email_uses_connected_mailbox_and_gmail_api(monkeypatch):
    engine = build_runtime()
    try:
        service = build_service(engine)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with Session(engine) as session:
            session.add(
                EmailConnection(
                    user_id="user-001",
                    provider="google",
                    email_address="owner@example.com",
                    encrypted_access_token=service._get_encryption_service().encrypt("access-token"),
                    encrypted_refresh_token=service._get_encryption_service().encrypt("refresh-token"),
                    token_expires_at=now + timedelta(hours=1),
                    scopes=service.SEND_SCOPE,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"id": "gmail-message-id", "threadId": "gmail-thread-id", "labelIds": ["SENT"]}).encode()

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse()

        monkeypatch.setattr("services.google_mail_oauth_service.urlopen", fake_urlopen)
        result = service.send_email(
            user_id="user-001",
            to="recipient@example.com",
            subject="NOVA test",
            body="NOVA test successful.",
        )
        assert result["status"] == "sent"
        assert result["message_id"] == "gmail-message-id"
        assert result["provider"] == "gmail"
        assert result["sent_label_confirmed"] is True
        assert result["from"] == "owner@example.com"
        assert captured["request"].get_header("Authorization") == "Bearer access-token"
        assert captured["timeout"] == service.HTTP_TIMEOUT_SECONDS
        payload = json.loads(captured["request"].data.decode())
        raw = payload["raw"]
        raw += "=" * (-len(raw) % 4)
        decoded = base64.urlsafe_b64decode(raw.encode())
        message = message_from_bytes(decoded)
        assert message["From"] == "owner@example.com"
        assert message["To"] == "recipient@example.com"
        assert message["Subject"] == "NOVA test"
        assert "NOVA test successful." in message.get_payload(decode=True).decode()
    finally:
        teardown_runtime(engine)


def test_send_email_requires_a_connected_user_mailbox():
    engine = build_runtime()
    try:
        service = build_service(engine)
        with pytest.raises(ValueError, match="Connect your Google/Gmail account"):
            service.send_email(
                user_id="user-001",
                to="recipient@example.com",
                subject="Hello",
                body="Test",
            )
    finally:
        teardown_runtime(engine)

def test_complete_authorization_rejects_missing_granted_scopes(monkeypatch):
    engine = build_runtime()
    try:
        service = build_service(engine)
        state = parse_qs(urlparse(service.build_authorization_url(user_id="user-001")).query)["state"][0]
        monkeypatch.setattr(
            service,
            "_post_form",
            lambda endpoint, payload, context: {
                "access_token": "raw-access-token",
                "refresh_token": "raw-refresh-token",
                "expires_in": 3600,
            },
        )
        with pytest.raises(ValueError, match="did not report the mailbox permissions"):
            service.complete_authorization(state=state, code="code")
        assert service.get_connection(user_id="user-001") is None
    finally:
        teardown_runtime(engine)


def test_send_email_reports_gmail_api_disabled_reason(monkeypatch):
    from urllib.error import HTTPError

    engine = build_runtime()
    try:
        service = build_service(engine)
        seed_connected_mailbox(engine, service)
        body = json.dumps({
            "error": {
                "code": 403,
                "message": "Gmail API has not been used in this project.",
                "errors": [{"domain": "usageLimits", "reason": "accessNotConfigured"}],
            }
        }).encode()

        def denied_urlopen(request, timeout):
            raise HTTPError(service.SEND_ENDPOINT, 403, "Forbidden", {}, BytesIO(body))

        monkeypatch.setattr("services.google_mail_oauth_service.urlopen", denied_urlopen)
        with pytest.raises(ValueError, match="Enable 'Gmail API' in that same Google Cloud project"):
            service.send_email(
                user_id="user-001",
                to="recipient@example.com",
                subject="NOVA test",
                body="NOVA test successful.",
            )
    finally:
        teardown_runtime(engine)


def test_send_email_does_not_claim_success_without_gmail_message_id(monkeypatch):
    engine = build_runtime()
    try:
        service = build_service(engine)
        seed_connected_mailbox(engine, service)

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"threadId": "gmail-thread-id"}).encode()

        monkeypatch.setattr(
            "services.google_mail_oauth_service.urlopen",
            lambda request, timeout: FakeResponse(),
        )
        with pytest.raises(ValueError, match="did not return a message ID"):
            service.send_email(
                user_id="user-001",
                to="recipient@example.com",
                subject="NOVA test",
                body="NOVA test successful.",
            )
    finally:
        teardown_runtime(engine)


def test_list_messages_fetches_limited_metadata_for_the_authenticated_mailbox(monkeypatch):
    engine = build_runtime()
    try:
        service = build_service(engine)
        seed_connected_mailbox(engine, service)
        captured = []

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(self.payload).encode()

        def fake_urlopen(request, timeout):
            captured.append((request, timeout))
            path = urlparse(request.full_url).path
            if path == urlparse(service.MESSAGES_ENDPOINT).path:
                return FakeResponse({
                    "messages": [{"id": "message_123", "threadId": "thread_123"}],
                    "resultSizeEstimate": 28,
                    "nextPageToken": "next-page",
                })
            return FakeResponse({
                "id": "message_123",
                "threadId": "thread_123",
                "snippet": "The meeting starts at ten.",
                "labelIds": ["INBOX", "UNREAD"],
                "payload": {"headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "To", "value": "owner@example.com"},
                    {"name": "Subject", "value": "Meeting"},
                    {"name": "Date", "value": "Sun, 18 Oct 2026 10:00:00 +0000"},
                ]},
            })

        monkeypatch.setattr("services.google_mail_oauth_service.urlopen", fake_urlopen)
        result = service.list_messages(user_id="user-001", max_results=3)

        assert result["query"] == "in:inbox"
        assert result["count"] == 1
        assert result["estimated_total"] == 28
        assert result["next_page_token"] == "next-page"
        assert result["messages"][0]["id"] == "message_123"
        assert result["messages"][0]["subject"] == "Meeting"
        assert result["messages"][0]["from"] == "sender@example.com"
        assert result["messages"][0]["labels"] == ["INBOX", "UNREAD"]
        assert len(captured) == 2
        assert all(req.get_header("Authorization") == "Bearer access-token" for req, _ in captured)
        assert "maxResults=3" in captured[0][0].full_url
    finally:
        teardown_runtime(engine)


def test_list_messages_requires_explicit_readonly_scope():
    engine = build_runtime()
    try:
        service = build_service(engine)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with Session(engine) as session:
            session.add(EmailConnection(
                user_id="user-001",
                provider="google",
                email_address="owner@example.com",
                encrypted_access_token=service._get_encryption_service().encrypt("access-token"),
                encrypted_refresh_token=service._get_encryption_service().encrypt("refresh-token"),
                token_expires_at=now + timedelta(hours=1),
                scopes=service.SEND_SCOPE,
                created_at=now,
                updated_at=now,
            ))
            session.commit()

        with pytest.raises(ValueError, match="read-only email permission"):
            service.list_messages(user_id="user-001")
    finally:
        teardown_runtime(engine)


def test_get_message_extracts_plain_text_and_never_returns_raw_html(monkeypatch):
    engine = build_runtime()
    try:
        service = build_service(engine)
        seed_connected_mailbox(engine, service)
        plain = base64.urlsafe_b64encode(b"Hello from the sender.").decode().rstrip("=")
        html = base64.urlsafe_b64encode(
            b"<html><head>hidden title</head><body><p>Hello from HTML</p><script>ignore this</script></body></html>"
        ).decode().rstrip("=")

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({
                    "id": "message_123",
                    "threadId": "thread_123",
                    "snippet": "Hello from the sender.",
                    "labelIds": ["INBOX"],
                    "payload": {
                        "mimeType": "multipart/alternative",
                        "headers": [
                            {"name": "From", "value": "sender@example.com"},
                            {"name": "To", "value": "owner@example.com"},
                            {"name": "Subject", "value": "Hello"},
                            {"name": "Date", "value": "Sun, 18 Oct 2026 10:00:00 +0000"},
                        ],
                        "parts": [
                            {"mimeType": "text/plain", "body": {"data": plain}},
                            {"mimeType": "text/html", "body": {"data": html}},
                        ],
                    },
                }).encode()

        monkeypatch.setattr(
            "services.google_mail_oauth_service.urlopen",
            lambda request, timeout: FakeResponse(),
        )
        result = service.get_message(user_id="user-001", message_id="message_123")

        assert result["subject"] == "Hello"
        assert result["body"] == "Hello from the sender."
        assert "<html>" not in result["body"]
        assert "ignore this" not in result["body"]
    finally:
        teardown_runtime(engine)


def test_get_message_rejects_invalid_id_before_network():
    engine = build_runtime()
    try:
        service = build_service(engine)
        with pytest.raises(ValueError, match="Gmail message ID is invalid"):
            service.get_message(user_id="user-001", message_id="../private")
    finally:
        teardown_runtime(engine)


def test_html_only_email_body_is_converted_to_text_without_script_content():
    html = base64.urlsafe_b64encode(
        b"<html><head><title>Hidden</title></head><body><p>Hello from HTML</p><script>ignore this</script></body></html>"
    ).decode().rstrip("=")

    body = GoogleMailOAuthService._extract_gmail_body({
        "mimeType": "text/html",
        "body": {"data": html},
    })

    assert "Hello from HTML" in body
    assert "Hidden" not in body
    assert "ignore this" not in body
    assert "<html>" not in body


def test_list_messages_includes_plain_text_bodies_only_when_requested(monkeypatch):
    engine = build_runtime()
    try:
        service = build_service(engine)
        seed_connected_mailbox(engine, service)
        encoded_body = base64.urlsafe_b64encode(
            b"The deadline is Friday at 3 PM."
        ).decode().rstrip("=")

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(self.payload).encode()

        def fake_urlopen(request, timeout):
            if urlparse(request.full_url).path == urlparse(service.MESSAGES_ENDPOINT).path:
                return FakeResponse({
                    "messages": [{"id": "message_123"}],
                    "resultSizeEstimate": 1,
                })
            return FakeResponse({
                "id": "message_123",
                "threadId": "thread_123",
                "snippet": "The deadline is Friday.",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "Subject", "value": "Deadline"},
                    ],
                    "body": {"data": encoded_body},
                },
            })

        monkeypatch.setattr("services.google_mail_oauth_service.urlopen", fake_urlopen)
        result = service.list_messages(
            user_id="user-001",
            max_results=1,
            include_body=True,
        )

        assert result["count"] == 1
        assert result["messages"][0]["subject"] == "Deadline"
        assert result["messages"][0]["body"] == "The deadline is Friday at 3 PM."
    finally:
        teardown_runtime(engine)
