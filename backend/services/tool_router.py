from datetime import datetime
from typing import Any

from services.activity_event_service import (
    ActivityEventService,
)
from services.notification_service import NotificationService
from services.reminder_service import ReminderService
from services.task_service import TaskService
from services.tool_registry import ToolRegistry


class ToolRouter:
    """
    Central router for NOVA's executable capabilities.

    The router maps a high-level intent to a registered tool.
    Individual tools remain responsible for their own actions.

    The registry keeps tool discovery, registration,
    metadata, and execution separate from the routing layer.

    Activity events are recorded after meaningful task/reminder
    state-changing operations. Activity recording is best-effort
    and never changes the success/failure of the underlying tool.

    Future tools such as:
    - calendar
    - email
    - messaging
    - web
    - documents
    - system APIs

    can be added without turning this router into one large
    hard-coded routing layer.
    """

    ACTIVITY_ACTIONS = {
        "create",
        "update",
        "start",
        "complete",
        "cancel",
        "delete",
        "send",
    }

    def __init__(
        self,
        reminder_service: ReminderService | None = None,
        task_service: TaskService | None = None,
        registry: ToolRegistry | None = None,
        activity_event_service: (
            ActivityEventService | None
        ) = None,
        notification_service: NotificationService | None = None,
    ):
        self.reminder_service = (
            reminder_service
            or ReminderService()
        )

        self.task_service = (
            task_service
            or TaskService()
        )

        self.registry = registry or ToolRegistry()

        self.activity_event_service = (
            activity_event_service
            if activity_event_service is not None
            else ActivityEventService()
        )

        self.notification_service = notification_service

        self._register_default_tools()

    # =====================================================
    # TOOL REGISTRATION
    # =====================================================

    def _register_default_tools(self) -> None:
        """
        Register NOVA's currently available tools.
        """

        if not self.registry.has("reminder"):
            self.registry.register(
                name="reminder",
                description=(
                    "Create, list, complete, cancel, "
                    "delete, and update reminders."
                ),
                actions=(
                    "create",
                    "list",
                    "complete",
                    "cancel",
                    "delete",
                    "update",
                ),
                handler=self._execute_reminder,
            )

        if not self.registry.has("task"):
            self.registry.register(
                name="task",
                description=(
                    "Create, list, start, complete, "
                    "cancel, delete, and update tasks."
                ),
                actions=(
                    "create",
                    "list",
                    "start",
                    "complete",
                    "cancel",
                    "delete",
                    "update",
                ),
                handler=self._execute_task,
            )

        if not self.registry.has("email"):
            self.registry.register(
                name="email",
                description=(
                    "Send outbound email messages to recipients "
                    "using NOVA's configured email provider."
                ),
                actions=("send",),
                handler=self._execute_email,
            )

    # =====================================================
    # TOOL DISCOVERY
    # =====================================================

    def get_available_tools(self) -> list[dict[str, Any]]:
        """
        Return metadata for tools currently available to NOVA.

        This method is intended for future planner/agent layers
        so they can inspect NOVA's capabilities without needing
        direct access to tool handlers.
        """

        return self.registry.get_available_tools()

    # =====================================================
    # CENTRAL EXECUTION
    # =====================================================

    def execute(
        self,
        intent: str,
        user_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        tool_name = str(intent).strip()
        payload = data or {}

        result = self.registry.execute(
            name=tool_name,
            user_id=user_id,
            data=payload,
        )

        self._record_tool_activity(
            user_id=user_id,
            tool_name=tool_name,
            payload=payload,
            result=result,
        )

        return result

    # =====================================================
    # ACTIVITY EVENT INSTRUMENTATION
    # =====================================================

    def _record_tool_activity(
        self,
        *,
        user_id: str,
        tool_name: str,
        payload: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        """
        Record meaningful task/reminder state changes.

        Activity persistence is intentionally best-effort.
        A logging failure must never change the tool result.
        """

        normalized_tool = (
            str(tool_name)
            .strip()
            .lower()
        )

        if normalized_tool not in {
            "task",
            "reminder",
            "email",
        }:
            return

        action = (
            result.get("action")
            or payload.get(
                "task_action"
                if normalized_tool == "task"
                else (
                    "reminder_action"
                    if normalized_tool == "reminder"
                    else "action"
                )
            )
        )

        if action is None:
            return

        normalized_action = (
            str(action)
            .strip()
            .lower()
        )

        if normalized_action not in self.ACTIVITY_ACTIONS:
            return

        success = (
            result.get("success")
            is True
        )

        event_type = (
            f"{normalized_tool}_{normalized_action}"
            if success
            else (
                f"{normalized_tool}_"
                f"{normalized_action}_failed"
            )
        )

        event_status = (
            "success"
            if success
            else "failed"
        )

        result_data = result.get(
            "result"
        )

        if not isinstance(
            result_data,
            dict,
        ):
            result_data = {}

        entity_id = (
            result_data.get(
                "task_id"
            )
            if normalized_tool == "task"
            else (
                result_data.get(
                    "reminder_id"
                )
                if normalized_tool == "reminder"
                else None
            )
        )

        title = (
            result_data.get("subject")
            if normalized_tool == "email"
            else result_data.get("title")
        )

        event_title = (
            self._build_activity_title(
                tool=normalized_tool,
                action=normalized_action,
                success=success,
                entity_id=entity_id,
                title=title,
            )
        )

        summary = (
            self._build_activity_summary(
                tool=normalized_tool,
                action=normalized_action,
                success=success,
                entity_id=entity_id,
                title=title,
                error=result.get(
                    "error"
                ),
            )
        )

        metadata: dict[str, Any] = {
            "tool": normalized_tool,
            "action": normalized_action,
        }

        if entity_id is not None:
            metadata["entity_id"] = entity_id

        if title is not None:
            metadata["title"] = str(title)

        returned_status = result_data.get(
            "status"
        )

        if returned_status is not None:
            metadata["result_status"] = (
                str(returned_status)
            )

        if normalized_tool == "email":
            email_subject = result_data.get(
                "subject"
            )

            if email_subject is not None:
                metadata["subject"] = str(
                    email_subject
                )[:200]

            recipient_count = 0

            for recipient_field in (
                "to",
                "cc",
                "bcc",
            ):
                recipients = result_data.get(
                    recipient_field
                )

                if isinstance(
                    recipients,
                    str,
                ):
                    recipient_count += len(
                        [
                            item
                            for item in recipients.split(",")
                            if item.strip()
                        ]
                    )
                elif isinstance(
                    recipients,
                    (list, tuple),
                ):
                    recipient_count += len(
                        [
                            item
                            for item in recipients
                            if str(item).strip()
                        ]
                    )

            if recipient_count > 0:
                metadata["recipient_count"] = (
                    recipient_count
                )

        try:
            self.activity_event_service.record_event(
                user_id=user_id,
                event_type=event_type,
                source="tool_router",
                status=event_status,
                title=event_title,
                summary=summary,
                metadata=metadata,
            )

        except Exception:
            # Activity logging must never break the real tool.
            # The underlying action has already produced its result.
            return

    @staticmethod
    def _build_activity_title(
        *,
        tool: str,
        action: str,
        success: bool,
        entity_id: Any,
        title: Any,
    ) -> str:
        noun = {
            "task": "Task",
            "reminder": "Reminder",
            "email": "Email",
        }.get(tool, tool.capitalize())

        verb_map = {
            "create": "created",
            "update": "updated",
            "start": "started",
            "complete": "completed",
            "cancel": "cancelled",
            "delete": "deleted",
            "send": "sent",
        }

        verb = verb_map.get(
            action,
            action,
        )

        if not success:
            verb = f"{verb} failed"

        if title:
            return (
                f"{noun} {verb}: "
                f"{str(title)[:150]}"
            )

        if entity_id is not None:
            return (
                f"{noun} {verb} "
                f"(ID {entity_id})"
            )

        return (
            f"{noun} {verb}"
        )

    @staticmethod
    def _build_activity_summary(
        *,
        tool: str,
        action: str,
        success: bool,
        entity_id: Any,
        title: Any,
        error: Any,
    ) -> str:
        noun = {
            "task": "task",
            "reminder": "reminder",
            "email": "email",
        }.get(tool, tool)

        if not success:
            error_text = (
                str(error).strip()
                if error
                else "The operation failed."
            )

            return (
                f"{noun.capitalize()} action "
                f"'{action}' failed: "
                f"{error_text}"
            )

        if title:
            identity = (
                f"'{str(title)[:200]}'"
            )
        elif entity_id is not None:
            identity = (
                f"ID {entity_id}"
            )
        else:
            identity = "the requested item"

        return (
            f"{noun.capitalize()} action "
            f"'{action}' succeeded for "
            f"{identity}."
        )

    # =====================================================
    # EMAIL
    # =====================================================

    def _execute_email(
        self,
        user_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        if self.notification_service is None:
            return {
                "success": False,
                "tool": "email",
                "action": "send",
                "result": None,
                "error": "Email delivery is not configured.",
            }

        action = str(
            data.get("action")
            or "send"
        ).strip().lower()

        if action != "send":
            return {
                "success": False,
                "tool": "email",
                "action": action,
                "result": None,
                "error": "Unsupported email action.",
            }

        subject = str(
            data.get("subject")
            or ""
        ).strip()

        body = str(
            data.get("body")
            or ""
        ).strip()

        to = data.get("to")
        cc = data.get("cc")
        bcc = data.get("bcc")

        if not subject:
            return {
                "success": False,
                "tool": "email",
                "action": "send",
                "result": None,
                "error": "Email subject is missing.",
            }

        if not body:
            return {
                "success": False,
                "tool": "email",
                "action": "send",
                "result": None,
                "error": "Email body is missing.",
            }

        try:
            success = self.notification_service.send_email(
                user_id=user_id,
                to=to,
                subject=subject,
                body=body,
                cc=cc,
                bcc=bcc,
            )
        except (ValueError, TypeError) as exc:
            return {
                "success": False,
                "tool": "email",
                "action": "send",
                "result": None,
                "error": str(exc),
            }
        except Exception:
            return {
                "success": False,
                "tool": "email",
                "action": "send",
                "result": None,
                "error": "Email delivery failed.",
            }

        if not success:
            return {
                "success": False,
                "tool": "email",
                "action": "send",
                "result": None,
                "error": "Email delivery failed.",
            }

        return {
            "success": True,
            "tool": "email",
            "action": "send",
            "result": {
                "status": "sent",
                "to": to,
                "cc": cc,
                "bcc": bcc,
                "subject": subject[:200],
            },
            "error": None,
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
                reminder_datetime = datetime.fromisoformat(
                    str(scheduled_at)
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