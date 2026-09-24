from __future__ import annotations

from datetime import datetime
from typing import Any

from services.google_calendar_service import (
    GoogleCalendarService,
)


class GoogleCalendarToolService:
    """
    Tool-facing adapter for Google Calendar.

    The adapter translates NOVA's generic tool payloads into the
    provider service API and normalizes results into the standard
    ToolRouter response shape.

    Provider construction is lazy so importing or constructing the
    adapter does not require Google OAuth configuration.
    """

    ACTIONS = (
        "list",
        "get",
        "create",
        "update",
        "delete",
    )

    DESCRIPTION = (
        "List, retrieve, create, update, and delete Google Calendar events."
    )

    def __init__(
        self,
        *,
        calendar_service: GoogleCalendarService | None = None,
    ):
        self._calendar_service = calendar_service

    @property
    def calendar_service(self) -> GoogleCalendarService:
        if self._calendar_service is None:
            self._calendar_service = GoogleCalendarService()

        return self._calendar_service

    def execute(
        self,
        *,
        user_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        action = str(
            data.get("calendar_action")
            or data.get("action")
            or ""
        ).strip().lower()

        if action not in self.ACTIONS:
            return self._failure(
                action=action,
                error="Unsupported calendar action.",
            )

        try:
            result = self._dispatch(
                user_id=user_id,
                action=action,
                data=data,
            )

        except (ValueError, TypeError) as exc:
            return self._failure(
                action=action,
                error=str(exc),
            )

        except Exception:
            return self._failure(
                action=action,
                error="Google Calendar operation failed.",
            )

        return {
            "success": True,
            "tool": "calendar",
            "action": action,
            "result": result,
            "error": None,
        }

    def _dispatch(
        self,
        *,
        user_id: str,
        action: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        calendar_id = data.get("calendar_id")

        if action == "list":
            return self.calendar_service.list_events(
                user_id=user_id,
                calendar_id=calendar_id,
                time_min=self._optional_datetime(
                    data.get("time_min")
                ),
                time_max=self._optional_datetime(
                    data.get("time_max")
                ),
                query=data.get("query"),
                max_results=self._optional_int(
                    data.get("max_results"),
                    default=(
                        self.calendar_service.DEFAULT_MAX_RESULTS
                    ),
                ),
                page_token=data.get("page_token"),
                single_events=self._optional_bool(
                    data.get("single_events"),
                    default=True,
                ),
                order_by=str(
                    data.get("order_by")
                    or "startTime"
                ),
                show_deleted=self._optional_bool(
                    data.get("show_deleted"),
                    default=False,
                ),
            )

        if action == "get":
            event_id = self._require_string(
                data.get("event_id"),
                "event_id",
            )

            return self._normalize_event_result(
                self.calendar_service.get_event(
                    user_id=user_id,
                    event_id=event_id,
                    calendar_id=calendar_id,
                )
            )

        if action == "create":
            create_kwargs = {
                "user_id": user_id,
                "event": self._require_event(
                    data.get("event")
                ),
                "calendar_id": calendar_id,
                "send_updates": self._send_updates(
                    data
                ),
            }

            idempotency_key = data.get(
                "idempotency_key"
            )

            if idempotency_key is not None:
                create_kwargs["idempotency_key"] = (
                    idempotency_key
                )

            return self._normalize_event_result(
                self.calendar_service.create_event(
                    **create_kwargs
                )
            )

        event_id = self._require_string(
            data.get("event_id"),
            "event_id",
        )

        if action == "update":
            update_kwargs = {
                "user_id": user_id,
                "event_id": event_id,
                "event": self._require_event(
                    data.get("event")
                ),
                "calendar_id": calendar_id,
                "send_updates": self._send_updates(
                    data
                ),
            }

            if data.get("if_match") is not None:
                update_kwargs["if_match"] = data["if_match"]

            return self._normalize_event_result(
                self.calendar_service.update_event(
                    **update_kwargs
                )
            )

        delete_kwargs = {
            "user_id": user_id,
            "event_id": event_id,
            "calendar_id": calendar_id,
            "send_updates": self._send_updates(
                data
            ),
        }

        if data.get("if_match") is not None:
            delete_kwargs["if_match"] = data["if_match"]

        return self.calendar_service.delete_event(
            **delete_kwargs
        )

    @staticmethod
    def _normalize_event_result(
        result: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(result)

        event_id = (
            normalized.get("event_id")
            or normalized.get("id")
        )

        if event_id is not None:
            normalized["event_id"] = str(event_id)

        return normalized

    @staticmethod
    def _require_string(
        value: Any,
        field_name: str,
    ) -> str:
        if not isinstance(value, str):
            raise ValueError(
                f"{field_name} is required."
            )

        normalized = value.strip()

        if not normalized:
            raise ValueError(
                f"{field_name} is required."
            )

        return normalized

    @staticmethod
    def _require_event(
        value: Any,
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(
                "Calendar event payload is required."
            )

        return value

    @staticmethod
    def _optional_datetime(
        value: Any,
    ) -> datetime | str | None:
        if value is None:
            return None

        if isinstance(value, datetime):
            return value

        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return None

            return normalized

        raise ValueError(
            "Calendar datetime filters must be strings or datetime values."
        )

    @staticmethod
    def _optional_int(
        value: Any,
        *,
        default: int,
    ) -> int:
        if value is None:
            return default

        if isinstance(value, bool):
            raise ValueError(
                "Calendar integer options must be integers."
            )

        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Calendar integer options must be integers."
            ) from exc

    @staticmethod
    def _optional_bool(
        value: Any,
        *,
        default: bool,
    ) -> bool:
        if value is None:
            return default

        if isinstance(value, bool):
            return value

        raise ValueError(
            "Calendar boolean options must be booleans."
        )

    @staticmethod
    def _send_updates(
        data: dict[str, Any],
    ) -> str:
        value = data.get(
            "send_updates"
        )

        if value is None:
            return GoogleCalendarService.DEFAULT_SEND_UPDATES

        if not isinstance(value, str):
            raise ValueError(
                "send_updates must be a string."
            )

        return value.strip() or (
            GoogleCalendarService.DEFAULT_SEND_UPDATES
        )

    @staticmethod
    def _failure(
        *,
        action: str,
        error: str,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "tool": "calendar",
            "action": action or None,
            "result": None,
            "error": error,
        }