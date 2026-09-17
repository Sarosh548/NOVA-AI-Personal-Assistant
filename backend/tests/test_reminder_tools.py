from datetime import datetime, timedelta, timezone

from services.tool_router import ToolRouter


class FakeReminderService:
    def __init__(self):
        self.completed_ids = []
        self.cancelled_ids = []
        self.deleted_ids = []
        self.updated_calls = []

    def create_reminder(
        self,
        user_id,
        title,
        reminder_time,
    ):
        return 101

    def get_pending_reminders(
        self,
        user_id,
    ):
        return [
            {
                "id": 101,
                "title": "submit CV",
                "reminder_time": datetime(
                    2030,
                    1,
                    1,
                    10,
                    0,
                ),
                "status": "pending",
            }
        ]

    def find_matching_reminders(
        self,
        user_id,
        reference,
    ):
        if reference == "submit CV":
            return [
                {
                    "id": 101,
                    "title": "submit CV",
                    "reminder_time": datetime(
                        2030,
                        1,
                        1,
                        10,
                        0,
                    ),
                    "status": "pending",
                }
            ]

        return []

    def complete_reminder(
        self,
        reminder_id,
        user_id,
    ):
        self.completed_ids.append(
            reminder_id
        )
        return True

    def cancel_reminder(
        self,
        reminder_id,
        user_id,
    ):
        self.cancelled_ids.append(
            reminder_id
        )
        return True

    def delete_reminder(
        self,
        reminder_id,
        user_id,
    ):
        self.deleted_ids.append(
            reminder_id
        )
        return True

    def update_reminder(
        self,
        reminder_id,
        user_id,
        title=None,
        reminder_time=None,
    ):
        self.updated_calls.append(
            {
                "reminder_id": reminder_id,
                "user_id": user_id,
                "title": title,
                "reminder_time": reminder_time,
            }
        )
        return True


def test_reminder_list_routes_to_service():
    fake_service = FakeReminderService()

    router = ToolRouter(
        reminder_service=fake_service
    )

    result = router.execute(
        intent="reminder",
        user_id="test-user",
        data={
            "reminder_action": "list",
        },
    )

    assert result["success"] is True
    assert result["tool"] == "reminder"
    assert result["action"] == "list"
    assert result["result"]["count"] == 1


def test_reminder_complete_uses_natural_reference():
    fake_service = FakeReminderService()

    router = ToolRouter(
        reminder_service=fake_service
    )

    result = router.execute(
        intent="reminder",
        user_id="test-user",
        data={
            "reminder_action": "complete",
            "reminder_id": None,
            "reminder_reference": "submit CV",
        },
    )

    assert result["success"] is True
    assert result["tool"] == "reminder"
    assert result["action"] == "complete"
    assert result["result"]["reminder_id"] == 101
    assert result["result"]["status"] == "completed"

    assert fake_service.completed_ids == [101]


def test_reminder_cancel_uses_natural_reference():
    fake_service = FakeReminderService()

    router = ToolRouter(
        reminder_service=fake_service
    )

    result = router.execute(
        intent="reminder",
        user_id="test-user",
        data={
            "reminder_action": "cancel",
            "reminder_id": None,
            "reminder_reference": "submit CV",
        },
    )

    assert result["success"] is True
    assert result["action"] == "cancel"
    assert result["result"]["reminder_id"] == 101
    assert result["result"]["status"] == "cancelled"

    assert fake_service.cancelled_ids == [101]


def test_reminder_delete_uses_natural_reference():
    fake_service = FakeReminderService()

    router = ToolRouter(
        reminder_service=fake_service
    )

    result = router.execute(
        intent="reminder",
        user_id="test-user",
        data={
            "reminder_action": "delete",
            "reminder_id": None,
            "reminder_reference": "submit CV",
        },
    )

    assert result["success"] is True
    assert result["action"] == "delete"
    assert result["result"]["reminder_id"] == 101
    assert result["result"]["status"] == "deleted"

    assert fake_service.deleted_ids == [101]


def test_reminder_update_changes_time():
    fake_service = FakeReminderService()

    router = ToolRouter(
        reminder_service=fake_service
    )

    future_time = (
        datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )
        + timedelta(
            hours=2
        )
    )

    result = router.execute(
        intent="reminder",
        user_id="test-user",
        data={
            "reminder_action": "update",
            "reminder_id": 101,
            "reminder_reference": None,
            "task": None,
            "scheduled_at": future_time.isoformat(),
        },
    )

    assert result["success"] is True
    assert result["tool"] == "reminder"
    assert result["action"] == "update"
    assert result["result"]["reminder_id"] == 101

    assert len(
        fake_service.updated_calls
    ) == 1

    assert (
        fake_service.updated_calls[0][
            "reminder_id"
        ]
        == 101
    )


def test_reminder_update_requires_reference_when_id_missing():
    fake_service = FakeReminderService()

    router = ToolRouter(
        reminder_service=fake_service
    )

    result = router.execute(
        intent="reminder",
        user_id="test-user",
        data={
            "reminder_action": "update",
            "reminder_id": None,
            "reminder_reference": None,
            "task": None,
            "scheduled_at": (
                "2030-01-01T10:00:00+05:00"
            ),
        },
    )

    assert result["success"] is False
    assert result["error"] == (
        "Reminder reference is missing."
    )


def test_reminder_update_requires_a_change():
    fake_service = FakeReminderService()

    router = ToolRouter(
        reminder_service=fake_service
    )

    result = router.execute(
        intent="reminder",
        user_id="test-user",
        data={
            "reminder_action": "update",
            "reminder_id": 101,
            "reminder_reference": None,
            "task": None,
            "scheduled_at": None,
        },
    )

    assert result["success"] is False
    assert result["error"] == (
        "No reminder fields were provided "
        "for update."
    )


def test_reminder_wrong_reference_fails_safely():
    fake_service = FakeReminderService()

    router = ToolRouter(
        reminder_service=fake_service
    )

    result = router.execute(
        intent="reminder",
        user_id="test-user",
        data={
            "reminder_action": "cancel",
            "reminder_id": None,
            "reminder_reference": "unknown reminder",
        },
    )

    assert result["success"] is False
    assert result["error"] == (
        "Could not find a matching "
        "pending reminder."
    )