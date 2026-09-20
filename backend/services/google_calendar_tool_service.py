from __future__ import annotations

from typing import Any

from services.google_calendar_service import (
    GoogleCalendarAPIError,
    GoogleCalendarService,
)


class GoogleCalendarToolService:
    """
    Translate NOVA's generic tool payload into Google Calendar
    event-service operations.

    Provider HTTP/authentication remains owned by the underlying
    GoogleCalendarService. This layer only defines the executable
    tool contract and keeps state-changing results minimal.
    """

    ACTIONS = (
        "list",
        "get",
        "create",
        "update",
        "delete",
    )

    def __init__(
        self,
        *,
        calendar_service: GoogleCalendarService | None = None,
    ):
        self.calendar_service = (
            calendar_service
            if calendar_service is not None
            else None
        )

    def execute(
        self,
        *,
        user_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(
            data,
            dict,
        ):
            return self._failure(
                action=None,
                error="Calendar tool data must be a dictionary.",
            )

        action = (
            str(
                data.get("calendar_action")
                or data.get("action")
                or ""
            )
            .strip()
            .lower()
        )

        if action not in self.ACTIONS:
            return self._failure(
                action=action or None,
                error="Unsupported calendar action.",
            )

        service = self._get_service()

        try:
            if action == "list":
                result = service.list_events(
                    user_id=user_id,
                    calendar_id=data.get("calendar_id"),
                    time_min=data.get("time_min"),
                    time_max=data.get("time_max"),
                    query=data.get("query"),
                    max_results=data.get(
                        "max_results",
                        GoogleCalendarService.DEFAULT_MAX_RESULTS,
                    ),
                    page_token=data.get("page_token"),
                    single_events=data.get(
                        "single_events",
                        True,
                    ),
                    order_by=data.get(
                        "order_by",
                        "startTime",
                    ),
                    show_deleted=data.get(
                        "show_deleted",
                        False,
                    ),
                )

            elif action == "get":
                result = service.get_event(
                    user_id=user_id,
                    event_id=data.get("event_id"),
                    calendar_id=data.get("calendar_id"),
                )

            elif action == "create":
                provider_result = service.create_event(
                    user_id=user_id,
                    event=data.get("event"),
                    calendar_id=data.get("calendar_id"),
                    send_updates=data.get(
                        "send_updates",
                        GoogleCalendarService.DEFAULT_SEND_UPDATES,
                    ),
                )
                result = self._state_change_result(
                    provider_result,
                    status="created",
                )

            elif action == "update":
                provider_result = service.update_event(
                    user_id=user_id,
                    event_id=data.get("event_id"),
                    event=data.get("event"),
                    calendar_id=data.get("calendar_id"),
                    send_updates=data.get(
                        "send_updates",
                        GoogleCalendarService.DEFAULT_SEND_UPDATES,
                    ),
                )
                result = self._state_change_result(
                    provider_result,
                    status="updated",
                )

            else:
                result = service.delete_event(
                    user_id=user_id,
                    event_id=data.get("event_id"),
                    calendar_id=data.get("calendar_id"),
                    send_updates=data.get(
                        "send_updates",
                        GoogleCalendarService.DEFAULT_SEND_UPDATES,
                    ),
                )

        except (
            ValueError,
            GoogleCalendarAPIError,
        ) as exc:
            return self._failure(
                action=action,
                error=str(exc),
            )

        return {
            "success": True,
            "tool": "calendar",
            "action": action,
            "result": result,
            "error": None,
        }

    def _get_service(self) -> GoogleCalendarService:
        if self.calendar_service is None:
            self.calendar_service = (
                GoogleCalendarService()
            )

        return self.calendar_service

    @staticmethod
    def _state_change_result(
        result: Any,
        *,
        status: str,
    ) -> dict[str, Any]:
        if not isinstance(
            result,
            dict,
        ):
            return {
                "status": status,
            }

        event_id = result.get("id")

        payload = {
            "status": status,
        }

        if event_id is not None:
            payload["event_id"] = event_id

        return payload

    @staticmethod
    def _failure(
        *,
        action: str | None,
        error: str,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "tool": "calendar",
            "action": action,
            "result": None,
            "error": error,
        }
