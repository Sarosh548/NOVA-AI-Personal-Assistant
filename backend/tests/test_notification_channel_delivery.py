from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import MagicMock, patch

import pytest

from services.notification_service import (
    EmailNotificationChannel,
    Notification,
    NotificationChannelRegistry,
    NotificationService,
    WebhookNotificationChannel,
)


class FakeNotificationChannel:
    def __init__(
        self,
        result=True,
    ):
        self.result = result
        self.notifications = []

    def send(
        self,
        notification: Notification,
    ) -> bool:
        self.notifications.append(
            notification
        )

        return self.result


class RecordingHTTPServer(
    HTTPServer
):
    def __init__(
        self,
        server_address,
        handler_class,
        *,
        response_status=200,
    ):
        super().__init__(
            server_address,
            handler_class,
        )

        self.response_status = (
            response_status
        )
        self.received_requests = []


class RecordingHandler(
    BaseHTTPRequestHandler
):
    def do_POST(
        self,
    ):
        content_length = int(
            self.headers.get(
                "Content-Length",
                "0",
            )
        )

        body = self.rfile.read(
            content_length
        )

        self.server.received_requests.append(
            {
                "path": self.path,
                "headers": {
                    key.lower(): value
                    for key, value in self.headers.items()
                },
                "body": body,
            }
        )

        self.send_response(
            self.server.response_status
        )

        self.send_header(
            "Content-Type",
            "application/json",
        )

        self.end_headers()

        self.wfile.write(
            b'{"ok":true}'
        )

    def log_message(
        self,
        format,
        *args,
    ):
        return


@pytest.fixture
def webhook_server():
    server = RecordingHTTPServer(
        (
            "127.0.0.1",
            0,
        ),
        RecordingHandler,
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )

    thread.start()

    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(
            timeout=2
        )


def test_notification_channel_registry_registers_and_resolves_channels():
    registry = NotificationChannelRegistry()

    channel = FakeNotificationChannel()

    registry.register(
        "test",
        channel,
    )

    assert registry.has("test")
    assert registry.get("test") is channel
    assert registry.list_channels() == [
        "test"
    ]


def test_notification_channel_registry_rejects_duplicate_channels():
    registry = NotificationChannelRegistry()

    registry.register(
        "test",
        FakeNotificationChannel(),
    )

    with pytest.raises(
        ValueError,
        match="already registered",
    ):
        registry.register(
            "test",
            FakeNotificationChannel(),
        )


def test_notification_channel_registry_unregisters_channels():
    registry = NotificationChannelRegistry()

    registry.register(
        "test",
        FakeNotificationChannel(),
    )

    assert registry.unregister(
        "test"
    ) is True

    assert registry.has(
        "test"
    ) is False

    assert registry.unregister(
        "test"
    ) is False


def test_notification_service_can_route_to_explicit_channel():
    console_channel = FakeNotificationChannel()
    webhook_like_channel = FakeNotificationChannel()

    registry = NotificationChannelRegistry()

    registry.register(
        "console",
        console_channel,
    )

    registry.register(
        "external",
        webhook_like_channel,
    )

    service = NotificationService(
        channel_registry=registry,
        default_channel="console",
    )

    result = service.notify(
        user_id="user-001",
        title="External test",
        body="Hello from NOVA.",
        notification_type="test",
        channel="external",
    )

    assert result is True
    assert len(
        console_channel.notifications
    ) == 0

    assert len(
        webhook_like_channel.notifications
    ) == 1


def test_notification_service_rejects_unknown_channel():
    service = NotificationService(
        channel=FakeNotificationChannel()
    )

    result = service.notify(
        user_id="user-001",
        title="Test",
        body="Unknown channel.",
        notification_type="test",
        channel="missing",
    )

    assert result is False


def test_notification_service_resolves_default_email_destination():
    channel = FakeNotificationChannel()

    class FakeDestinationService:
        def get_default_destination(
            self,
            *,
            user_id,
            channel,
        ):
            assert user_id == "user-001"
            assert channel == "email"

            return {
                "id": 42,
                "destination": "sarosh@example.com",
            }

    service = NotificationService(
        channel=channel,
        destination_service=(
            FakeDestinationService()
        ),
        default_channel="email",
    )

    result = service.notify(
        user_id="user-001",
        title="Email test",
        body="Hello.",
        notification_type="test",
    )

    assert result is True

    assert (
        channel.notifications[0].destination
        == "sarosh@example.com"
    )


def test_notification_service_allows_explicit_email_destination():
    channel = FakeNotificationChannel()

    service = NotificationService(
        channel=channel,
        default_channel="email",
    )

    result = service.notify(
        user_id="user-001",
        title="Email test",
        body="Hello.",
        notification_type="test",
        destination="explicit@example.com",
    )

    assert result is True
    assert (
        channel.notifications[0].destination
        == "explicit@example.com"
    )


def test_email_channel_sends_message():
    smtp_client = MagicMock()

    smtp_class = MagicMock()

    smtp_class.return_value.__enter__.return_value = (
        smtp_client
    )

    channel = EmailNotificationChannel(
        host="smtp.example.com",
        port=587,
        from_address="nova@example.com",
        username="smtp-user",
        password="smtp-password",
        starttls=True,
        use_ssl=False,
    )

    notification = Notification(
        user_id="user-001",
        notification_type="workflow",
        title="NOVA completed",
        body="Your background workflow completed.",
        destination="sarosh@example.com",
    )

    with patch(
        "services.notification_service.smtplib.SMTP",
        smtp_class,
    ):
        result = channel.send(
            notification
        )

    assert result is True

    smtp_class.assert_called_once_with(
        "smtp.example.com",
        587,
        timeout=10,
    )

    smtp_client.starttls.assert_called_once_with()

    smtp_client.login.assert_called_once_with(
        "smtp-user",
        "smtp-password",
    )

    smtp_client.send_message.assert_called_once()

    message = (
        smtp_client
        .send_message
        .call_args[0][0]
    )

    assert message["From"] == (
        "nova@example.com"
    )

    assert message["To"] == (
        "sarosh@example.com"
    )

    assert message["Subject"] == (
        "NOVA completed"
    )

    assert (
        message.get_content()
        == (
            "Your background workflow completed.\n"
        )
    )


def test_email_channel_uses_ssl_without_starttls():
    smtp_client = MagicMock()

    smtp_class = MagicMock()

    smtp_class.return_value.__enter__.return_value = (
        smtp_client
    )

    channel = EmailNotificationChannel(
        host="smtp.example.com",
        port=465,
        from_address="nova@example.com",
        use_ssl=True,
        starttls=False,
    )

    notification = Notification(
        user_id="user-001",
        notification_type="general",
        title="Test",
        body="SSL email.",
        destination="sarosh@example.com",
    )

    with patch(
        "services.notification_service.smtplib.SMTP_SSL",
        smtp_class,
    ):
        result = channel.send(
            notification
        )

    assert result is True
    smtp_client.starttls.assert_not_called()
    smtp_client.login.assert_not_called()
    smtp_client.send_message.assert_called_once()


def test_email_channel_requires_destination():
    channel = EmailNotificationChannel(
        host="smtp.example.com",
        port=587,
        from_address="nova@example.com",
    )

    notification = Notification(
        user_id="user-001",
        notification_type="general",
        title="Test",
        body="No destination.",
    )

    assert (
        channel.send(
            notification
        )
        is False
    )


def test_email_channel_returns_false_for_smtp_failure():
    smtp_client = MagicMock()

    smtp_class = MagicMock()

    smtp_class.return_value.__enter__.return_value = (
        smtp_client
    )

    smtp_client.send_message.side_effect = (
        OSError(
            "SMTP unavailable"
        )
    )

    channel = EmailNotificationChannel(
        host="smtp.example.com",
        port=587,
        from_address="nova@example.com",
    )

    notification = Notification(
        user_id="user-001",
        notification_type="general",
        title="Test",
        body="SMTP failure.",
        destination="sarosh@example.com",
    )

    with patch(
        "services.notification_service.smtplib.SMTP",
        smtp_class,
    ):
        result = channel.send(
            notification
        )

    assert result is False


def test_email_channel_rejects_invalid_configuration():
    with pytest.raises(
        ValueError,
        match="cannot both be enabled",
    ):
        EmailNotificationChannel(
            host="smtp.example.com",
            port=587,
            from_address="nova@example.com",
            starttls=True,
            use_ssl=True,
        )


def test_webhook_channel_sends_notification_payload(
    webhook_server,
):
    channel = WebhookNotificationChannel(
        endpoint_url=(
            f"http://127.0.0.1:"
            f"{webhook_server.server_port}/notify"
        ),
        secret="test-secret",
    )

    service = NotificationService(
        channel=channel
    )

    result = service.notify(
        user_id="user-001",
        title="NOVA test",
        body="Webhook delivery works.",
        notification_type="workflow",
        metadata={
            "workflow_id": 42,
            "status": "completed",
        },
    )

    assert result is True
    assert len(
        webhook_server.received_requests
    ) == 1

    request = (
        webhook_server
        .received_requests[0]
    )

    assert request["path"] == (
        "/notify"
    )

    assert (
        request["headers"]
        ["content-type"]
        == "application/json"
    )

    assert (
        request["headers"]
        ["x-nova-notification-secret"]
        == "test-secret"
    )

    payload = json.loads(
        request["body"].decode(
            "utf-8"
        )
    )

    assert payload == {
        "user_id": "user-001",
        "notification_type": (
            "workflow"
        ),
        "title": "NOVA test",
        "body": (
            "Webhook delivery works."
        ),
        "metadata": {
            "workflow_id": 42,
            "status": "completed",
        },
    }


def test_webhook_channel_returns_false_for_non_success_response(
    webhook_server,
):
    webhook_server.response_status = 503

    channel = WebhookNotificationChannel(
        endpoint_url=(
            f"http://127.0.0.1:"
            f"{webhook_server.server_port}/notify"
        ),
    )

    service = NotificationService(
        channel=channel
    )

    result = service.notify(
        user_id="user-001",
        title="Test",
        body="Provider unavailable.",
        notification_type="test",
    )

    assert result is False


def test_webhook_channel_returns_false_when_endpoint_is_unavailable():
    channel = WebhookNotificationChannel(
        endpoint_url=(
            "http://127.0.0.1:1/notify"
        ),
        timeout_seconds=1,
    )

    service = NotificationService(
        channel=channel
    )

    result = service.notify(
        user_id="user-001",
        title="Test",
        body="Endpoint unavailable.",
        notification_type="test",
    )

    assert result is False


@pytest.mark.parametrize(
    "endpoint_url",
    [
        "",
        "ftp://example.com/notify",
        "not-a-url",
        "https:///missing-host",
    ],
)
def test_webhook_channel_rejects_invalid_endpoint(
    endpoint_url,
):
    with pytest.raises(
        ValueError,
    ):
        WebhookNotificationChannel(
            endpoint_url=endpoint_url,
        )


def test_webhook_channel_rejects_invalid_timeout():
    with pytest.raises(
        ValueError,
        match="timeout_seconds",
    ):
        WebhookNotificationChannel(
            endpoint_url=(
                "https://example.com/notify"
            ),
            timeout_seconds=0,
        )