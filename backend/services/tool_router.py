from datetime import datetime
from typing import Any

from services.reminder_service import ReminderService
from services.task_service import TaskService


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
        task_service: TaskService | None = None,
    ):
        self.reminder_service = (
            reminder_service
            or ReminderService()
        )

        self.task_service = (
            task_service
            or TaskService()
        )

    def execute(
        self,
        intent: str,
        user_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        payload = data or {}

        if intent == "reminder":
            return self._execute_reminder(
                user_id=user_id,
                data=payload,
            )

        if intent == "task":
            return self._execute_task(
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

    # =====================================================
    # REMINDER
    # =====================================================

    def _execute_reminder(
        self,
        user_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:

        reminder_action = (
            data.get("reminder_action")
            or "create"
        )

        if reminder_action == "create":
            return self._create_reminder(
                user_id=user_id,
                data=data,
            )

        if reminder_action == "list":
            return self._list_reminders(
                user_id=user_id,
            )

        if reminder_action == "complete":
            return self._complete_reminder(
                user_id=user_id,
                data=data,
            )

        if reminder_action == "cancel":
            return self._cancel_reminder(
                user_id=user_id,
                data=data,
            )

        if reminder_action == "delete":
            return self._delete_reminder(
                user_id=user_id,
                data=data,
            )

        if reminder_action == "update":
            return self._update_reminder(
                user_id=user_id,
                data=data,
            )

        return {
            "success": False,
            "tool": "reminder",
            "action": reminder_action,
            "result": None,
            "error": "Unsupported reminder action.",
        }

    def _create_reminder(
        self,
        user_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:

        task = (
            data.get("task")
            or self._extract_reminder_title(
                data.get("action")
            )
        )

        scheduled_at = data.get("scheduled_at")

        if not task:
            return {
                "success": False,
                "tool": "reminder",
                "action": "create",
                "result": None,
                "error": "Reminder task is missing.",
            }

        if not scheduled_at:
            return {
                "success": False,
                "tool": "reminder",
                "action": "create",
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
                "action": "create",
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
                "action": "create",
                "result": None,
                "error": str(exc),
            }

        return {
            "success": True,
            "tool": "reminder",
            "action": "create",
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

    def _list_reminders(
        self,
        user_id: str,
    ) -> dict[str, Any]:

        reminders = (
            self.reminder_service
            .get_pending_reminders(
                user_id=user_id,
            )
        )

        return {
            "success": True,
            "tool": "reminder",
            "action": "list",
            "result": {
                "reminders": reminders,
                "count": len(reminders),
            },
            "error": None,
        }

    def _resolve_reminder_id(
        self,
        user_id: str,
        data: dict[str, Any],
    ) -> tuple[int | None, dict[str, Any] | None]:

        reminder_id = data.get("reminder_id")

        if reminder_id is not None:
            try:
                reminder_id = int(reminder_id)
            except (TypeError, ValueError):
                return None, {
                    "success": False,
                    "tool": "reminder",
                    "action": None,
                    "result": None,
                    "error": "Invalid reminder ID.",
                }

            if reminder_id < 1:
                return None, {
                    "success": False,
                    "tool": "reminder",
                    "action": None,
                    "result": None,
                    "error": "Invalid reminder ID.",
                }

            return reminder_id, None

        reminder_reference = (
            data.get("reminder_reference")
            or data.get("task")
        )

        if not reminder_reference:
            return None, {
                "success": False,
                "tool": "reminder",
                "action": None,
                "result": None,
                "error": "Reminder reference is missing.",
            }

        matches = (
            self.reminder_service
            .find_matching_reminders(
                user_id=user_id,
                reference=str(reminder_reference),
            )
        )

        if len(matches) == 0:
            return None, {
                "success": False,
                "tool": "reminder",
                "action": None,
                "result": None,
                "error": (
                    "Could not find a matching "
                    "pending reminder."
                ),
            }

        if len(matches) > 1:
            return None, {
                "success": False,
                "tool": "reminder",
                "action": None,
                "result": {
                    "matches": matches,
                    "count": len(matches),
                },
                "error": (
                    "Multiple matching reminders found. "
                    "Reminder selection is ambiguous."
                ),
            }

        return matches[0]["id"], None

    def _complete_reminder(
        self,
        user_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:

        reminder_id, error = (
            self._resolve_reminder_id(
                user_id=user_id,
                data=data,
            )
        )

        if error:
            error["action"] = "complete"
            return error

        success = (
            self.reminder_service
            .complete_reminder(
                reminder_id=reminder_id,
                user_id=user_id,
            )
        )

        if not success:
            return {
                "success": False,
                "tool": "reminder",
                "action": "complete",
                "result": None,
                "error": "Reminder not found.",
            }

        return {
            "success": True,
            "tool": "reminder",
            "action": "complete",
            "result": {
                "reminder_id": reminder_id,
                "status": "completed",
            },
            "error": None,
        }

    def _cancel_reminder(
        self,
        user_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:

        reminder_id, error = (
            self._resolve_reminder_id(
                user_id=user_id,
                data=data,
            )
        )

        if error:
            error["action"] = "cancel"
            return error

        success = (
            self.reminder_service
            .cancel_reminder(
                reminder_id=reminder_id,
                user_id=user_id,
            )
        )

        if not success:
            return {
                "success": False,
                "tool": "reminder",
                "action": "cancel",
                "result": None,
                "error": "Reminder not found.",
            }

        return {
            "success": True,
            "tool": "reminder",
            "action": "cancel",
            "result": {
                "reminder_id": reminder_id,
                "status": "cancelled",
            },
            "error": None,
        }

    def _delete_reminder(
        self,
        user_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:

        reminder_id, error = (
            self._resolve_reminder_id(
                user_id=user_id,
                data=data,
            )
        )

        if error:
            error["action"] = "delete"
            return error

        success = (
            self.reminder_service
            .delete_reminder(
                reminder_id=reminder_id,
                user_id=user_id,
            )
        )

        if not success:
            return {
                "success": False,
                "tool": "reminder",
                "action": "delete",
                "result": None,
                "error": "Reminder not found.",
            }

        return {
            "success": True,
            "tool": "reminder",
            "action": "delete",
            "result": {
                "reminder_id": reminder_id,
                "status": "deleted",
            },
            "error": None,
        }

    def _update_reminder(
        self,
        user_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:

        reminder_id, error = (
            self._resolve_reminder_id(
                user_id=user_id,
                data=data,
            )
        )

        if error:
            error["action"] = "update"
            return error

        title = data.get("task")
        scheduled_at = data.get("scheduled_at")

        if title is None and scheduled_at is None:
            return {
                "success": False,
                "tool": "reminder",
                "action": "update",
                "result": None,
                "error": (
                    "No reminder fields were provided "
                    "for update."
                ),
            }

        reminder_datetime = None

        if scheduled_at is not None:
            try:
                reminder_datetime = (
                    datetime.fromisoformat(
                        str(scheduled_at)
                    )
                )
            except ValueError:
                return {
                    "success": False,
                    "tool": "reminder",
                    "action": "update",
                    "result": None,
                    "error": "Invalid reminder datetime.",
                }

        try:
            success = (
                self.reminder_service
                .update_reminder(
                    reminder_id=reminder_id,
                    user_id=user_id,
                    title=(
                        str(title)
                        if title is not None
                        else None
                    ),
                    reminder_time=reminder_datetime,
                )
            )

        except ValueError as exc:
            return {
                "success": False,
                "tool": "reminder",
                "action": "update",
                "result": None,
                "error": str(exc),
            }

        if not success:
            return {
                "success": False,
                "tool": "reminder",
                "action": "update",
                "result": None,
                "error": "Reminder not found.",
            }

        return {
            "success": True,
            "tool": "reminder",
            "action": "update",
            "result": {
                "reminder_id": reminder_id,
                "title": (
                    str(title)
                    if title is not None
                    else None
                ),
                "scheduled_at": (
                    str(scheduled_at)
                    if scheduled_at is not None
                    else None
                ),
            },
            "error": None,
        }

    def _extract_reminder_title(
        self,
        action: Any,
    ) -> str | None:

        if not action:
            return None

        text = str(action).strip()

        if not text:
            return None

        prefixes = (
            "reminder to ",
            "remind me to ",
            "reminder: ",
            "remind me ",
        )

        lowered = text.lower()

        for prefix in prefixes:
            if lowered.startswith(prefix):
                text = text[len(prefix):].strip()
                break

        return text or None

    # =====================================================
    # TASK
    # =====================================================

    def _execute_task(
        self,
        user_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:

        task_action = data.get("task_action")

        if not task_action:
            return {
                "success": False,
                "tool": "task",
                "action": None,
                "result": None,
                "error": "Task action is missing.",
            }

        if task_action == "create":
            return self._create_task(
                user_id=user_id,
                data=data,
            )

        if task_action == "list":
            return self._list_tasks(
                user_id=user_id,
            )

        if task_action == "update":
            return self._update_task(
                user_id=user_id,
                data=data,
            )

        task_id = data.get("task_id")

        if task_id is None:
            task_reference = (
                data.get("task_reference")
                or data.get("task")
            )

            if not task_reference:
                return {
                    "success": False,
                    "tool": "task",
                    "action": task_action,
                    "result": None,
                    "error": "Task reference is missing.",
                }

            matches = (
                self.task_service
                .find_matching_tasks(
                    user_id=user_id,
                    reference=str(task_reference),
                )
            )

            if len(matches) == 0:
                return {
                    "success": False,
                    "tool": "task",
                    "action": task_action,
                    "result": None,
                    "error": (
                        "Could not find a matching "
                        "pending task."
                    ),
                }

            if len(matches) > 1:
                return {
                    "success": False,
                    "tool": "task",
                    "action": task_action,
                    "result": {
                        "matches": matches,
                        "count": len(matches),
                    },
                    "error": (
                        "Multiple matching tasks found. "
                        "Task selection is ambiguous."
                    ),
                }

            task_id = matches[0]["id"]

        if task_action == "start":
            success = self.task_service.start_task(
                task_id=int(task_id),
                user_id=user_id,
            )

        elif task_action == "complete":
            success = self.task_service.complete_task(
                task_id=int(task_id),
                user_id=user_id,
            )

        elif task_action == "cancel":
            success = self.task_service.cancel_task(
                task_id=int(task_id),
                user_id=user_id,
            )

        elif task_action == "delete":
            success = self.task_service.delete_task(
                task_id=int(task_id),
                user_id=user_id,
            )

        else:
            return {
                "success": False,
                "tool": "task",
                "action": task_action,
                "result": None,
                "error": "Unsupported task action.",
            }

        if not success:
            return {
                "success": False,
                "tool": "task",
                "action": task_action,
                "result": None,
                "error": "Task not found.",
            }

        status = (
            "in_progress"
            if task_action == "start"
            else (
                "completed"
                if task_action == "complete"
                else (
                    "cancelled"
                    if task_action == "cancel"
                    else (
                        "deleted"
                        if task_action == "delete"
                        else None
                    )
                )
            )
        )

        return {
            "success": True,
            "tool": "task",
            "action": task_action,
            "result": {
                "task_id": int(task_id),
                "status": status,
            },
            "error": None,
        }

    def _update_task(
        self,
        user_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:

        task_id = data.get("task_id")

        if task_id is None:
            task_reference = (
                data.get("task_reference")
                or data.get("task")
            )

            if not task_reference:
                return {
                    "success": False,
                    "tool": "task",
                    "action": "update",
                    "result": None,
                    "error": "Task reference is missing.",
                }

            matches = (
                self.task_service
                .find_matching_tasks(
                    user_id=user_id,
                    reference=str(task_reference),
                )
            )

            if len(matches) == 0:
                return {
                    "success": False,
                    "tool": "task",
                    "action": "update",
                    "result": None,
                    "error": (
                        "Could not find a matching "
                        "pending task."
                    ),
                }

            if len(matches) > 1:
                return {
                    "success": False,
                    "tool": "task",
                    "action": "update",
                    "result": {
                        "matches": matches,
                        "count": len(matches),
                    },
                    "error": (
                        "Multiple matching tasks found. "
                        "Task selection is ambiguous."
                    ),
                }

            task_id = matches[0]["id"]

        priority = data.get("priority")
        scheduled_at = data.get("scheduled_at")

        if priority is None and scheduled_at is None:
            return {
                "success": False,
                "tool": "task",
                "action": "update",
                "result": None,
                "error": (
                    "No task fields were provided "
                    "for update."
                ),
            }

        due_at = None

        if scheduled_at is not None:
            try:
                due_at = datetime.fromisoformat(
                    str(scheduled_at)
                )
            except ValueError:
                return {
                    "success": False,
                    "tool": "task",
                    "action": "update",
                    "result": None,
                    "error": "Invalid task due datetime.",
                }

        try:
            success = self.task_service.update_task(
                task_id=int(task_id),
                user_id=user_id,
                priority=priority,
                due_at=due_at,
            )

        except ValueError as exc:
            return {
                "success": False,
                "tool": "task",
                "action": "update",
                "result": None,
                "error": str(exc),
            }

        if not success:
            return {
                "success": False,
                "tool": "task",
                "action": "update",
                "result": None,
                "error": "Task not found.",
            }

        return {
            "success": True,
            "tool": "task",
            "action": "update",
            "result": {
                "task_id": int(task_id),
                "priority": priority,
                "due_at": (
                    str(scheduled_at)
                    if scheduled_at
                    else None
                ),
            },
            "error": None,
        }

    def _create_task(
        self,
        user_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:

        task_title = data.get("task")
        priority = data.get("priority") or "medium"
        scheduled_at = data.get("scheduled_at")

        if not task_title:
            return {
                "success": False,
                "tool": "task",
                "action": "create",
                "result": None,
                "error": "Task title is missing.",
            }

        due_at = None

        if scheduled_at:
            try:
                due_at = datetime.fromisoformat(
                    str(scheduled_at)
                )
            except ValueError:
                return {
                    "success": False,
                    "tool": "task",
                    "action": "create",
                    "result": None,
                    "error": "Invalid task due datetime.",
                }

        try:
            task_id = self.task_service.create_task(
                user_id=user_id,
                title=str(task_title),
                priority=str(priority),
                due_at=due_at,
            )

        except ValueError as exc:
            return {
                "success": False,
                "tool": "task",
                "action": "create",
                "result": None,
                "error": str(exc),
            }

        return {
            "success": True,
            "tool": "task",
            "action": "create",
            "result": {
                "task_id": task_id,
                "title": str(task_title),
                "priority": str(priority),
                "due_at": (
                    str(scheduled_at)
                    if scheduled_at
                    else None
                ),
                "status": "pending",
            },
            "error": None,
        }

    def _list_tasks(
        self,
        user_id: str,
    ) -> dict[str, Any]:

        tasks = self.task_service.get_tasks(
            user_id=user_id,
        )

        return {
            "success": True,
            "tool": "task",
            "action": "list",
            "result": {
                "tasks": tasks,
                "count": len(tasks),
            },
            "error": None,
        }