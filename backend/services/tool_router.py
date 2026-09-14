from datetime import datetime
from typing import Any

from services.reminder_service import ReminderService


class ToolRouter:
    """
    Central router for NOVA's executable capabilities.

    The user never selects a tool directly.
    NOVA's understanding layer decides which capability
    is required, and this router executes it.
    """

    def __init__(
        self,
        reminder_service: ReminderService | None = None,
    ):
        self.reminder_service = (
            reminder_service
            or ReminderService()
        )

    def execute(
        self,
        intent: str,
        user_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute the capability associated with an intent.
        """

        payload = data or {}

        if intent == "reminder":
            return self._execute_reminder(
                user_id=user_id,
                data=payload,
            )

        return {
            "success": False,
            "tool": None,
            "action": None,
            "result": None,
            "error": (
                f"No tool is registered for intent "
                f"'{intent}'."
            ),
        }

    def _execute_reminder(
        self,
        user_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Create a reminder using validated structured data.
        """

        task = data.get("task")
        scheduled_at = data.get("scheduled_at")

        if not task:
            return {
                "success": False,
                "tool": "reminder",
                "action": "create_reminder",
                "result": None,
                "error": "Reminder task is missing.",
            }

        if not scheduled_at:
            return {
                "success": False,
                "tool": "reminder",
                "action": "create_reminder",
                "result": None,
                "error": "Reminder time is missing.",
            }

        try:
            reminder_datetime = datetime.fromisoformat(
                str(scheduled_at)
            )
        except ValueError:
            return {
                "success": False,
                "tool": "reminder",
                "action": "create_reminder",
                "result": None,
                "error": "Invalid reminder datetime.",
            }

        try:
            reminder_id = (
                self.reminder_service
                .create_reminder(
                    user_id=user_id,
                    title=str(task),
                    reminder_time=reminder_datetime,
                )
            )

        except ValueError as exc:
            return {
                "success": False,
                "tool": "reminder",
                "action": "create_reminder",
                "result": None,
                "error": str(exc),
            }

        return {
            "success": True,
            "tool": "reminder",
            "action": "create_reminder",
            "result": {
                "reminder_id": reminder_id,
                "title": str(task),
                "scheduled_at": str(
                    scheduled_at
                ),
                "status": "pending",
            },
            "error": None,
        }
