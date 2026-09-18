import pytest

from services.reminder_scheduler import (
    ReminderScheduler,
)
from services.tool_router import ToolRouter


class FakeActivityEventService:
    def __init__(self):
        self.events = []

    def record_event(
        self,
        **kwargs,
    ):
        self.events.append(
            kwargs
        )

        return {
            "id": len(self.events),
            **kwargs,
        }


class FakeTaskService:
    def __init__(self):
        self.created_ids = []

    def create_task(
        self,
        user_id,
        title,
        priority="medium",
        due_at=None,
    ):
        self.created_ids.append(
            501
        )
        return 501

    def get_tasks(
        self,
        user_id,
        status=None,
    ):
        return []

    def find_matching_tasks(
        self,
        user_id,
        reference,
    ):
        return [
            {
                "id": 501,
                "title": "Practice Python",
                "description": None,
                "status": "pending",
                "priority": "medium",
                "due_at": None,
            }
        ]

    def update_task(
        self,
        task_id,
        user_id,
        priority=None,
        due_at=None,
    ):
        return True

    def start_task(
        self,
        task_id,
        user_id,
    ):
        return True

    def complete_task(
        self,
        task_id,
        user_id,
    ):
        return True

    def cancel_task(
        self,
        task_id,
        user_id,
    ):
        return True

    def delete_task(
        self,
        task_id,
        user_id,
    ):
        return True


class FakeReminderService:
    def __init__(
        self,
        *,
        complete_result=True,
    ):
        self.completed_ids = []
        self.pending_ids = []
        self.complete_result = (
            complete_result
        )

    def create_reminder(
        self,
        user_id,
        title,
        reminder_time,
    ):
        return 601

    def get_pending_reminders(
        self,
        user_id,
    ):
        return []

    def find_matching_reminders(
        self,
        user_id,
        reference,
    ):
        return [
            {
                "id": 601,
                "title": "Submit CV",
                "reminder_time": None,
                "status": "pending",
            }
        ]

    def complete_reminder(
        self,
        reminder_id,
        user_id,
    ):
        return True

    def cancel_reminder(
        self,
        reminder_id,
        user_id,
    ):
        return True

    def delete_reminder(
        self,
        reminder_id,
        user_id,
    ):
        return True

    def update_reminder(
        self,
        reminder_id,
        user_id,
        title=None,
        reminder_time=None,
    ):
        return True

    def claim_due_reminders(self):
        return [
            {
                "id": 601,
                "user_id": "test-user",
                "title": "Submit CV",
                "reminder_time": None,
                "status": "processing",
            }
        ]

    def mark_reminder_completed(
        self,
        reminder_id,
    ):
        if self.complete_result:
            self.completed_ids.append(
                reminder_id
            )

        return self.complete_result

    def mark_reminder_pending(
        self,
        reminder_id,
    ):
        self.pending_ids.append(
            reminder_id
        )
        return True


class FakeNotificationService:
    def __init__(
        self,
        result=True,
    ):
        self.result = result
        self.notifications = []

    def notify(
        self,
        **kwargs,
    ):
        self.notifications.append(
            kwargs
        )

        return self.result


def test_tool_router_records_successful_task_change():
    activity_service = (
        FakeActivityEventService()
    )

    router = ToolRouter(
        task_service=FakeTaskService(),
        activity_event_service=activity_service,
    )

    result = router.execute(
        intent="task",
        user_id="test-user",
        data={
            "task_action": "create",
            "task": "Practice Python",
            "priority": "high",
        },
    )

    assert result["success"] is True
    assert len(
        activity_service.events
    ) == 1

    event = activity_service.events[0]

    assert (
        event["event_type"]
        == "task_create"
    )

    assert (
        event["status"]
        == "success"
    )

    assert (
        event["source"]
        == "tool_router"
    )

    assert (
        event["metadata"]["tool"]
        == "task"
    )

    assert (
        event["metadata"]["action"]
        == "create"
    )

    assert (
        event["metadata"]["entity_id"]
        == 501
    )

    assert (
        event["metadata"]["title"]
        == "Practice Python"
    )


def test_tool_router_records_failed_task_change():
    activity_service = (
        FakeActivityEventService()
    )

    class FailingTaskService(
        FakeTaskService
    ):
        def create_task(
            self,
            user_id,
            title,
            priority="medium",
            due_at=None,
        ):
            raise ValueError(
                "Task title cannot be empty."
            )

    router = ToolRouter(
        task_service=FailingTaskService(),
        activity_event_service=activity_service,
    )

    result = router.execute(
        intent="task",
        user_id="test-user",
        data={
            "task_action": "create",
            "task": "Test task",
            "priority": "medium",
        },
    )

    assert result["success"] is False
    assert len(
        activity_service.events
    ) == 1

    event = activity_service.events[0]

    assert (
        event["event_type"]
        == "task_create_failed"
    )

    assert (
        event["status"]
        == "failed"
    )

    assert (
        "Task title cannot be empty."
        in event["summary"]
    )


def test_tool_router_records_successful_reminder_change():
    activity_service = (
        FakeActivityEventService()
    )

    router = ToolRouter(
        reminder_service=FakeReminderService(),
        activity_event_service=activity_service,
    )

    result = router.execute(
        intent="reminder",
        user_id="test-user",
        data={
            "reminder_action": "complete",
            "reminder_id": 601,
            "reminder_reference": None,
        },
    )

    assert result["success"] is True
    assert len(
        activity_service.events
    ) == 1

    event = activity_service.events[0]

    assert (
        event["event_type"]
        == "reminder_complete"
    )

    assert (
        event["status"]
        == "success"
    )

    assert (
        event["metadata"]["entity_id"]
        == 601
    )


def test_tool_router_does_not_record_read_only_list():
    activity_service = (
        FakeActivityEventService()
    )

    router = ToolRouter(
        task_service=FakeTaskService(),
        activity_event_service=activity_service,
    )

    result = router.execute(
        intent="task",
        user_id="test-user",
        data={
            "task_action": "list",
        },
    )

    assert result["success"] is True
    assert (
        activity_service.events
        == []
    )


def test_tool_router_activity_failure_does_not_break_tool(
    monkeypatch,
):
    class FailingActivityEventService:
        def record_event(self, **kwargs):
            raise RuntimeError(
                "activity database unavailable"
            )

    router = ToolRouter(
        task_service=FakeTaskService(),
        activity_event_service=(
            FailingActivityEventService()
        ),
    )

    result = router.execute(
        intent="task",
        user_id="test-user",
        data={
            "task_action": "create",
            "task": "Practice Python",
            "priority": "medium",
        },
    )

    assert result["success"] is True


@pytest.mark.asyncio
async def test_scheduler_records_successful_reminder_completion():
    reminder_service = FakeReminderService()
    notification_service = (
        FakeNotificationService(
            result=True
        )
    )
    activity_service = (
        FakeActivityEventService()
    )

    scheduler = ReminderScheduler(
        interval_seconds=5,
        reminder_service=reminder_service,
        notification_service=notification_service,
        activity_event_service=activity_service,
    )

    await scheduler.process_due_reminders()

    assert (
        reminder_service.completed_ids
        == [601]
    )

    assert len(
        activity_service.events
    ) == 1

    event = activity_service.events[0]

    assert (
        event["event_type"]
        == "reminder_completed"
    )

    assert (
        event["status"]
        == "success"
    )

    assert (
        event["source"]
        == "reminder_scheduler"
    )

    assert (
        event["metadata"]["reminder_id"]
        == 601
    )


@pytest.mark.asyncio
async def test_scheduler_records_failed_delivery():
    reminder_service = FakeReminderService()
    notification_service = (
        FakeNotificationService(
            result=False
        )
    )
    activity_service = (
        FakeActivityEventService()
    )

    scheduler = ReminderScheduler(
        interval_seconds=5,
        reminder_service=reminder_service,
        notification_service=notification_service,
        activity_event_service=activity_service,
    )

    await scheduler.process_due_reminders()

    assert (
        reminder_service.completed_ids
        == []
    )

    assert (
        reminder_service.pending_ids
        == [601]
    )

    assert len(
        activity_service.events
    ) == 1

    event = activity_service.events[0]

    assert (
        event["event_type"]
        == "reminder_delivery_failed"
    )

    assert (
        event["status"]
        == "failed"
    )


@pytest.mark.asyncio
async def test_scheduler_records_notification_exception():
    reminder_service = FakeReminderService()
    activity_service = (
        FakeActivityEventService()
    )

    class FailingNotificationService:
        def notify(self, **kwargs):
            raise RuntimeError(
                "delivery failed"
            )

    scheduler = ReminderScheduler(
        interval_seconds=5,
        reminder_service=reminder_service,
        notification_service=(
            FailingNotificationService()
        ),
        activity_event_service=activity_service,
    )

    await scheduler.process_due_reminders()

    assert (
        reminder_service.pending_ids
        == [601]
    )

    assert len(
        activity_service.events
    ) == 1

    event = activity_service.events[0]

    assert (
        event["event_type"]
        == "reminder_delivery_failed"
    )

    assert (
        event["status"]
        == "failed"
    )


@pytest.mark.asyncio
async def test_scheduler_records_partial_when_completion_fails():
    reminder_service = FakeReminderService(
        complete_result=False
    )
    notification_service = (
        FakeNotificationService(
            result=True
        )
    )
    activity_service = (
        FakeActivityEventService()
    )

    scheduler = ReminderScheduler(
        interval_seconds=5,
        reminder_service=reminder_service,
        notification_service=notification_service,
        activity_event_service=activity_service,
    )

    await scheduler.process_due_reminders()

    assert (
        reminder_service.completed_ids
        == []
    )

    assert len(
        activity_service.events
    ) == 1

    event = activity_service.events[0]

    assert (
        event["event_type"]
        == "reminder_completion_failed"
    )

    assert (
        event["status"]
        == "partial"
    )


@pytest.mark.asyncio
async def test_scheduler_activity_failure_does_not_break_completion():
    reminder_service = FakeReminderService()
    notification_service = (
        FakeNotificationService(
            result=True
        )
    )

    class FailingActivityEventService:
        def record_event(self, **kwargs):
            raise RuntimeError(
                "activity database unavailable"
            )

    scheduler = ReminderScheduler(
        interval_seconds=5,
        reminder_service=reminder_service,
        notification_service=notification_service,
        activity_event_service=(
            FailingActivityEventService()
        ),
    )

    await scheduler.process_due_reminders()

    assert (
        reminder_service.completed_ids
        == [601]
    )