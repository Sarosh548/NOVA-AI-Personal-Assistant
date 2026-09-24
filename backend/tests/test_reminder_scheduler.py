import pytest

from services.reminder_scheduler import ReminderScheduler


CLAIM_TOKEN = "claim-token-101"


class FakeReminderService:
    def __init__(self):
        self.completed_calls = []
        self.pending_calls = []
        self.batch_sizes = []

    def claim_due_reminders(self, *, batch_size):
        self.batch_sizes.append(batch_size)

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
        idempotency_key,
    ):
        self.notifications.append(
            {
                "user_id": user_id,
                "title": title,
                "body": body,
                "notification_type": notification_type,
                "metadata": metadata,
                "idempotency_key": idempotency_key,
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

    assert reminder_service.batch_sizes == [50]

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
            "idempotency_key": "nova:reminder:101",
        }
    ]


@pytest.mark.asyncio
async def test_scheduler_reuses_stable_idempotency_key_on_retry():
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
    await scheduler.process_due_reminders()

    assert [
        item["idempotency_key"]
        for item in notification_service.notifications
    ] == [
        "nova:reminder:101",
        "nova:reminder:101",
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

    with pytest.raises(
        ValueError,
        match="interval_seconds must not exceed MAX_CYCLE_BACKOFF_SECONDS",
    ):
        ReminderScheduler(
            interval_seconds=(
                ReminderScheduler.MAX_CYCLE_BACKOFF_SECONDS + 1
            )
        )


@pytest.mark.asyncio
async def test_scheduler_run_survives_cycle_failure(monkeypatch):
    scheduler = ReminderScheduler()
    calls = []
    backoff_waits = []

    async def flaky_cycle():
        calls.append("cycle")

        if len(calls) == 1:
            raise RuntimeError(
                "simulated cycle failure"
            )

        scheduler.stop()

    async def fake_wait_for(awaitable, timeout):
        backoff_waits.append(timeout)
        awaitable.close()

    scheduler.process_due_reminders = flaky_cycle

    monkeypatch.setattr(
        "services.reminder_scheduler.asyncio.wait_for",
        fake_wait_for,
    )

    await scheduler.run()

    assert calls == [
        "cycle",
        "cycle",
    ]
    assert backoff_waits == [
        scheduler.interval_seconds
    ]
    assert scheduler._running is False


@pytest.mark.asyncio
async def test_scheduler_cycle_backoff_caps_and_resets_after_success(monkeypatch):
    scheduler = ReminderScheduler()
    calls = []
    backoff_waits = []

    async def flaky_cycle():
        calls.append("cycle")

        if len(calls) <= 5:
            raise RuntimeError(
                "simulated cycle failure"
            )

        if len(calls) == 7:
            raise RuntimeError(
                "simulated post-recovery failure"
            )

        if len(calls) == 8:
            scheduler.stop()

    async def fake_wait_for(awaitable, timeout):
        backoff_waits.append(timeout)
        awaitable.close()

    scheduler.process_due_reminders = flaky_cycle

    monkeypatch.setattr(
        "services.reminder_scheduler.asyncio.wait_for",
        fake_wait_for,
    )

    await scheduler.run()

    assert calls == [
        "cycle",
        "cycle",
        "cycle",
        "cycle",
        "cycle",
        "cycle",
        "cycle",
        "cycle",
    ]
    assert backoff_waits == [
        scheduler.interval_seconds,
        scheduler.interval_seconds * 2,
        scheduler.interval_seconds * 4,
        scheduler.interval_seconds * 8,
        scheduler.MAX_CYCLE_BACKOFF_SECONDS,
        scheduler.interval_seconds,
        scheduler.interval_seconds,
    ]
    assert scheduler._running is False



@pytest.mark.parametrize(
    "batch_size",
    [0, ReminderScheduler.MAX_BATCH_SIZE + 1],
)
def test_scheduler_rejects_invalid_batch_size(batch_size):
    with pytest.raises(
        ValueError,
        match="batch_size",
    ):
        ReminderScheduler(
            batch_size=batch_size,
        )
