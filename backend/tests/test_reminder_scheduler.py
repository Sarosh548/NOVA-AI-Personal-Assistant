import pytest

from services.reminder_scheduler import ReminderScheduler


class FakeReminderService:
    def __init__(self):
        self.completed_ids = []
        self.pending_ids = []

    def claim_due_reminders(self):
        return [
            {
                "id": 101,
                "user_id": "test-user",
                "title": "Test reminder",
                "reminder_time": None,
                "status": "processing",
            }
        ]

    def mark_reminder_completed(self, reminder_id):
        self.completed_ids.append(reminder_id)
        return True

    def mark_reminder_pending(self, reminder_id):
        self.pending_ids.append(reminder_id)
        return True


@pytest.mark.asyncio
async def test_scheduler_processes_due_reminder():
    scheduler = ReminderScheduler(
        interval_seconds=5
    )

    fake_service = FakeReminderService()
    scheduler.reminder_service = fake_service

    await scheduler.process_due_reminders()

    assert fake_service.completed_ids == [101]
    assert fake_service.pending_ids == []


@pytest.mark.asyncio
async def test_scheduler_returns_failed_reminder_to_pending():
    class FailingReminderService(FakeReminderService):

        def mark_reminder_completed(self, reminder_id):
            raise RuntimeError("Notification failed")

    scheduler = ReminderScheduler(
        interval_seconds=5
    )

    fake_service = FailingReminderService()
    scheduler.reminder_service = fake_service

    await scheduler.process_due_reminders()

    assert fake_service.completed_ids == []
    assert fake_service.pending_ids == [101]