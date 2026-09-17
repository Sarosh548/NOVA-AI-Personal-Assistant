import pytest

from services.notification_service import (
    Notification,
    NotificationService,
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