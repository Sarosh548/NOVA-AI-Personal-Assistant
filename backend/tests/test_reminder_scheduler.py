import pytest

from services.reminder_scheduler import ReminderScheduler


CLAIM_TOKEN = "claim-token-101"


class FakeReminderService:
    def __init__(self):
        self.completed_calls = []
        self.pending_calls = []

    def claim_due_reminders(self):
        return [
            {
                "id": 101,
                "user_id": "test-user",
                "title": "Test reminder",
                "reminder_time": None,
                "status": "processing",
                "claim_token": CLAIM_TOKEN,
                "lease_until": None,
            }
        ]

    def mark_reminder_completed(
        self,
        reminder_id,
        *,
        claim_token,
    ):
        self.completed_calls.append(
            {
                "reminder_id": reminder_id,
                "claim_token": claim_token,
            }
        )
        return True

    def mark_reminder_pending(
        self,
        reminder_id,
        *,
        claim_token,
    ):
        self.pending_calls.append(
            {
                "reminder_id": reminder_id,
                "claim_token": claim_token,
            }
        )
        return True


class FakeNotificationService:
    def __init__(self, result=True):
        self.result = result
        self.notifications = []

    def notify(
        self,
        *,
        user_id,
        title,
        body,
        notification_type,
        metadata,
    ):
        self.notifications.append(
            {
                "user_id": user_id,
                "title": title,
                "body": body,
                "notification_type": notification_type,
                "metadata": metadata,
            }
        )

        return self.result


@pytest.mark.asyncio
async def test_scheduler_processes_due_reminder_after_successful_notification():
    reminder_service = FakeReminderService()
    notification_service = FakeNotificationService(
        result=True
    )

    scheduler = ReminderScheduler(
        interval_seconds=5,
        reminder_service=reminder_service,
        notification_service=notification_service,
    )

    await scheduler.process_due_reminders()

    assert reminder_service.completed_calls == [
        {
            "reminder_id": 101,
            "claim_token": CLAIM_TOKEN,
        }
    ]
    assert reminder_service.pending_calls == []

    assert notification_service.notifications == [
        {
            "user_id": "test-user",
            "title": "NOVA Reminder",
            "body": "Test reminder",
            "notification_type": "reminder",
            "metadata": {
                "reminder_id": 101,
            },
        }
    ]


@pytest.mark.asyncio
async def test_scheduler_returns_failed_notification_to_pending():
    reminder_service = FakeReminderService()
    notification_service = FakeNotificationService(
        result=False
    )

    scheduler = ReminderScheduler(
        interval_seconds=5,
        reminder_service=reminder_service,
        notification_service=notification_service,
    )

    await scheduler.process_due_reminders()

    assert reminder_service.completed_calls == []
    assert reminder_service.pending_calls == [
        {
            "reminder_id": 101,
            "claim_token": CLAIM_TOKEN,
        }
    ]
    assert len(notification_service.notifications) == 1


@pytest.mark.asyncio
async def test_scheduler_returns_reminder_to_pending_when_notification_raises():
    reminder_service = FakeReminderService()

    class FailingNotificationService:
        def notify(self, **kwargs):
            raise RuntimeError(
                "Notification delivery failed"
            )

    scheduler = ReminderScheduler(
        interval_seconds=5,
        reminder_service=reminder_service,
        notification_service=FailingNotificationService(),
    )

    await scheduler.process_due_reminders()

    assert reminder_service.completed_calls == []
    assert reminder_service.pending_calls == [
        {
            "reminder_id": 101,
            "claim_token": CLAIM_TOKEN,
        }
    ]


@pytest.mark.asyncio
async def test_scheduler_keeps_reminder_processing_when_completion_loses_lease():
    reminder_service = FakeReminderService()
    notification_service = FakeNotificationService(
        result=True
    )

    reminder_service.mark_reminder_completed = (
        lambda reminder_id, *, claim_token: False
    )

    scheduler = ReminderScheduler(
        interval_seconds=5,
        reminder_service=reminder_service,
        notification_service=notification_service,
    )

    await scheduler.process_due_reminders()

    assert reminder_service.pending_calls == []


@pytest.mark.asyncio
async def test_scheduler_does_not_fail_when_returning_failed_reminder_to_pending_raises():
    reminder_service = FakeReminderService()
    notification_service = FakeNotificationService(
        result=False
    )

    def raise_on_pending(
        reminder_id,
        *,
        claim_token,
    ):
        raise RuntimeError(
            "database unavailable"
        )

    reminder_service.mark_reminder_pending = (
        raise_on_pending
    )

    scheduler = ReminderScheduler(
        interval_seconds=5,
        reminder_service=reminder_service,
        notification_service=notification_service,
    )

    await scheduler.process_due_reminders()

    assert len(notification_service.notifications) == 1


def test_scheduler_rejects_invalid_interval():
    with pytest.raises(
        ValueError,
        match="interval_seconds must be at least 1",
    ):
        ReminderScheduler(
            interval_seconds=0,
        )
