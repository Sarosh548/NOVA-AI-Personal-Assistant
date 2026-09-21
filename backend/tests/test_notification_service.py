import pytest

from services.notification_service import (
    EmailNotificationChannel,
    Notification,
    NotificationService,
    WebhookNotificationChannel,
)


class FakeNotificationChannel:
    def __init__(self, result=True):
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


class FailingNotificationChannel:
    def send(
        self,
        notification: Notification,
    ) -> bool:
        raise RuntimeError(
            "delivery failed"
        )


def test_notification_service_sends_notification():
    channel = FakeNotificationChannel()
    service = NotificationService(
        channel=channel
    )

    result = service.notify(
        user_id="user-001",
        title="Reminder",
        body="Submit your CV.",
        notification_type="reminder",
        metadata={
            "reminder_id": 42,
        },
    )

    assert result is True
    assert len(channel.notifications) == 1

    notification = channel.notifications[0]

    assert notification.user_id == "user-001"
    assert notification.notification_type == "reminder"
    assert notification.title == "Reminder"
    assert notification.body == "Submit your CV."
    assert notification.metadata == {
        "reminder_id": 42,
    }


def test_notification_service_returns_false_when_channel_fails():
    channel = FakeNotificationChannel(
        result=False
    )
    service = NotificationService(
        channel=channel
    )

    result = service.notify(
        user_id="user-001",
        title="Reminder",
        body="Submit your CV.",
        notification_type="reminder",
    )

    assert result is False
    assert len(channel.notifications) == 1


def test_notification_service_handles_channel_exception():
    service = NotificationService(
        channel=FailingNotificationChannel()
    )

    result = service.notify(
        user_id="user-001",
        title="Reminder",
        body="Submit your CV.",
        notification_type="reminder",
    )

    assert result is False


@pytest.mark.parametrize(
    "kwargs,expected_error",
    [
        (
            {
                "user_id": "",
                "title": "Reminder",
                "body": "Test",
            },
            "Notification user_id cannot be empty.",
        ),
        (
            {
                "user_id": "user-001",
                "title": "",
                "body": "Test",
            },
            "Notification title cannot be empty.",
        ),
        (
            {
                "user_id": "user-001",
                "title": "Reminder",
                "body": "",
            },
            "Notification body cannot be empty.",
        ),
        (
            {
                "user_id": "user-001",
                "title": "Reminder",
                "body": "Test",
                "notification_type": "",
            },
            "Notification type cannot be empty.",
        ),
    ],
)
def test_notification_service_validates_input(
    kwargs,
    expected_error,
):
    service = NotificationService(
        channel=FakeNotificationChannel()
    )

    with pytest.raises(
        ValueError,
        match=expected_error,
    ):
        service.notify(
            **kwargs
        )


def test_notification_service_copies_metadata():
    channel = FakeNotificationChannel()
    service = NotificationService(
        channel=channel
    )

    metadata = {
        "reminder_id": 10,
        "source": "scheduler",
    }

    service.notify(
        user_id="user-001",
        title="Reminder",
        body="Test",
        notification_type="reminder",
        metadata=metadata,
    )

    metadata["reminder_id"] = 999

    notification = channel.notifications[0]

    assert notification.metadata == {
        "reminder_id": 10,
        "source": "scheduler",
    }


def test_notification_service_forwards_idempotency_key():
    channel = FakeNotificationChannel()
    service = NotificationService(
        channel=channel
    )

    result = service.notify(
        user_id="user-001",
        title="Reminder",
        body="Test",
        notification_type="reminder",
        idempotency_key="nova:reminder:42",
    )

    assert result is True
    assert (
        channel.notifications[0].idempotency_key
        == "nova:reminder:42"
    )


@pytest.mark.parametrize(
    "idempotency_key,expected_error",
    [
        (
            "",
            "Notification idempotency_key cannot be empty.",
        ),
        (
            " " * 2,
            "Notification idempotency_key cannot be empty.",
        ),
    ],
)
def test_notification_service_validates_idempotency_key(
    idempotency_key,
    expected_error,
):
    service = NotificationService(
        channel=FakeNotificationChannel()
    )

    with pytest.raises(
        ValueError,
        match=expected_error,
    ):
        service.notify(
            user_id="user-001",
            title="Reminder",
            body="Test",
            idempotency_key=idempotency_key,
        )


def test_email_notification_uses_stable_message_id(
    monkeypatch,
):
    sent_messages = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, message):
            sent_messages.append(message)

    monkeypatch.setattr(
        "services.notification_service.smtplib.SMTP",
        FakeSMTP,
    )

    channel = EmailNotificationChannel(
        host="smtp.example.com",
        port=587,
        from_address="nova@example.com",
        starttls=False,
        use_ssl=False,
    )

    notification = Notification(
        user_id="user-001",
        notification_type="reminder",
        title="Reminder",
        body="Test",
        destination="user@example.com",
        idempotency_key="nova:reminder:42",
    )

    assert channel.send(notification) is True
    assert channel.send(notification) is True

    assert len(sent_messages) == 2
    assert (
        sent_messages[0]["Message-ID"]
        == sent_messages[1]["Message-ID"]
    )
    assert (
        sent_messages[0]["Message-ID"]
        == "<nova-"
        "a3d701cde2aa8f8c8f5e3edb9b5a9f1e"
        "@nova.local>"
    )


def test_webhook_notification_sends_idempotency_header(
    monkeypatch,
):
    captured = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        captured.append(
            {
                "request": request,
                "timeout": timeout,
            }
        )
        return FakeResponse()

    monkeypatch.setattr(
        "services.notification_service.urlopen",
        fake_urlopen,
    )

    channel = WebhookNotificationChannel(
        endpoint_url="https://example.com/notify",
        timeout_seconds=7,
    )

    notification = Notification(
        user_id="user-001",
        notification_type="reminder",
        title="Reminder",
        body="Test",
        idempotency_key="nova:reminder:42",
    )

    assert channel.send(notification) is True

    assert len(captured) == 1
    request = captured[0]["request"]

    assert (
        request.get_header("Idempotency-key")
        == "nova:reminder:42"
    )
    assert captured[0]["timeout"] == 7
