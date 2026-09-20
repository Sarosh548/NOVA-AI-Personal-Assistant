from __future__ import annotations

from datetime import datetime
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from services.google_calendar_oauth_service import (
    GoogleCalendarOAuthService,
)


class GoogleCalendarAPIError(ValueError):
    """
    Safe application error raised for Google Calendar API failures.

    Provider response bodies are intentionally not exposed because
    Calendar payloads can contain private event information.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code


class GoogleCalendarService:
    """
    Provider service for Google Calendar event operations.

    OAuth and encrypted credential lifecycle remain owned by
    GoogleCalendarOAuthService. This service only obtains a valid
    access token and performs Calendar API resource operations.

    Current supported operations:
    - list events
    - get event
    - create event
    - update event using PATCH semantics
    - delete event
    """

    BASE_URL = (
        "https://www.googleapis.com/calendar/v3"
    )

    DEFAULT_SEND_UPDATES = "all"

    VALID_SEND_UPDATES = {
        "all",
        "externalOnly",
        "none",
    }

    DEFAULT_MAX_RESULTS = 50
    MAX_MAX_RESULTS = 2500
    HTTP_TIMEOUT_SECONDS = 10

    def __init__(
        self,
        *,
        oauth_service: (
            GoogleCalendarOAuthService | None
        ) = None,
    ):
        self.oauth_service = (
            oauth_service
            if oauth_service is not None
            else GoogleCalendarOAuthService()
        )

    # =====================================================
    # LIST
    # =====================================================

    def list_events(
        self,
        *,
        user_id: str,
        calendar_id: str | None = None,
        time_min: datetime | str | None = None,
        time_max: datetime | str | None = None,
        query: str | None = None,
        max_results: int = DEFAULT_MAX_RESULTS,
        page_token: str | None = None,
        single_events: bool = True,
        order_by: str = "startTime",
        show_deleted: bool = False,
    ) -> dict[str, Any]:
        """
        List events from the connected user's calendar.

        The default query expands recurring events and orders them
        by start time, which is the useful shape for an assistant.
        """

        calendar = self._resolve_calendar_id(
            user_id=user_id,
            calendar_id=calendar_id,
        )

        if not isinstance(
            max_results,
            int,
        ) or isinstance(
            max_results,
            bool,
        ):
            raise ValueError(
                "max_results must be an integer."
            )

        if not (
            1
            <= max_results
            <= self.MAX_MAX_RESULTS
        ):
            raise ValueError(
                "max_results must be between 1 and 2500."
            )

        if order_by not in {
            "startTime",
            "updated",
        }:
            raise ValueError(
                "order_by must be 'startTime' or 'updated'."
            )

        params: list[tuple[str, str]] = []

        if time_min is not None:
            params.append(
                (
                    "timeMin",
                    self._format_datetime(
                        time_min
                    ),
                )
            )

        if time_max is not None:
            params.append(
                (
                    "timeMax",
                    self._format_datetime(
                        time_max
                    ),
                )
            )

        if query is not None:
            normalized_query = str(
                query
            ).strip()

            if normalized_query:
                params.append(
                    (
                        "q",
                        normalized_query,
                    )
                )

        params.extend(
            [
                (
                    "maxResults",
                    str(max_results),
                ),
                (
                    "singleEvents",
                    str(
                        single_events
                    ).lower(),
                ),
                (
                    "orderBy",
                    order_by,
                ),
                (
                    "showDeleted",
                    str(
                        show_deleted
                    ).lower(),
                ),
            ]
        )

        if page_token is not None:
            normalized_page_token = str(
                page_token
            ).strip()

            if normalized_page_token:
                params.append(
                    (
                        "pageToken",
                        normalized_page_token,
                    )
                )

        path = (
            f"/calendars/"
            f"{quote(calendar, safe='')}"
            "/events"
        )

        response = self._request(
            user_id=user_id,
            method="GET",
            path=path,
            query=params,
        )

        if not isinstance(
            response,
            dict,
        ):
            raise GoogleCalendarAPIError(
                "Google Calendar returned an invalid list response."
            )

        items = response.get(
            "items",
            [],
        )

        if not isinstance(
            items,
            list,
        ):
            raise GoogleCalendarAPIError(
                "Google Calendar returned an invalid event list."
            )

        return {
            "events": items,
            "next_page_token": response.get(
                "nextPageToken"
            ),
            "next_sync_token": response.get(
                "nextSyncToken"
            ),
        }

    # =====================================================
    # GET
    # =====================================================

    def get_event(
        self,
        *,
        user_id: str,
        event_id: str,
        calendar_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve one event by its Google Calendar event ID.
        """

        calendar = self._resolve_calendar_id(
            user_id=user_id,
            calendar_id=calendar_id,
        )

        normalized_event_id = (
            self._validate_identifier(
                event_id,
                "event_id",
            )
        )

        path = (
            f"/calendars/"
            f"{quote(calendar, safe='')}"
            "/events/"
            f"{quote(normalized_event_id, safe='')}"
        )

        response = self._request(
            user_id=user_id,
            method="GET",
            path=path,
        )

        if not isinstance(
            response,
            dict,
        ):
            raise GoogleCalendarAPIError(
                "Google Calendar returned an invalid event response."
            )

        return response

    # =====================================================
    # CREATE
    # =====================================================

    def create_event(
        self,
        *,
        user_id: str,
        event: dict[str, Any],
        calendar_id: str | None = None,
        send_updates: str = DEFAULT_SEND_UPDATES,
    ) -> dict[str, Any]:
        """
        Create a Calendar event.

        Google requires start and end on an event resource.
        """

        calendar = self._resolve_calendar_id(
            user_id=user_id,
            calendar_id=calendar_id,
        )

        payload = self._validate_event_payload(
            event
        )

        normalized_send_updates = (
            self._validate_send_updates(
                send_updates
            )
        )

        path = (
            f"/calendars/"
            f"{quote(calendar, safe='')}"
            "/events"
        )

        response = self._request(
            user_id=user_id,
            method="POST",
            path=path,
            query=[
                (
                    "sendUpdates",
                    normalized_send_updates,
                )
            ],
            body=payload,
        )

        if not isinstance(
            response,
            dict,
        ):
            raise GoogleCalendarAPIError(
                "Google Calendar returned an invalid create response."
            )

        return response

    # =====================================================
    # UPDATE
    # =====================================================

    def update_event(
        self,
        *,
        user_id: str,
        event_id: str,
        event: dict[str, Any],
        calendar_id: str | None = None,
        send_updates: str = DEFAULT_SEND_UPDATES,
    ) -> dict[str, Any]:
        """
        Partially update a Calendar event using Google's PATCH API.

        A caller only needs to provide fields that should change.
        If start or end is supplied, both should be present because
        they form the event's time boundary.
        """

        calendar = self._resolve_calendar_id(
            user_id=user_id,
            calendar_id=calendar_id,
        )

        normalized_event_id = (
            self._validate_identifier(
                event_id,
                "event_id",
            )
        )

        payload = self._validate_event_payload(
            event,
            require_start_end=False,
        )

        if (
            "start" in payload
            or "end" in payload
        ):
            if (
                "start" not in payload
                or "end" not in payload
            ):
                raise ValueError(
                    "Calendar event updates must include both start and end when changing event time."
                )

        normalized_send_updates = (
            self._validate_send_updates(
                send_updates
            )
        )

        if not payload:
            raise ValueError(
                "Calendar event update cannot be empty."
            )

        path = (
            f"/calendars/"
            f"{quote(calendar, safe='')}"
            "/events/"
            f"{quote(normalized_event_id, safe='')}"
        )

        response = self._request(
            user_id=user_id,
            method="PATCH",
            path=path,
            query=[
                (
                    "sendUpdates",
                    normalized_send_updates,
                )
            ],
            body=payload,
        )

        if not isinstance(
            response,
            dict,
        ):
            raise GoogleCalendarAPIError(
                "Google Calendar returned an invalid update response."
            )

        return response

    # =====================================================
    # DELETE
    # =====================================================

    def delete_event(
        self,
        *,
        user_id: str,
        event_id: str,
        calendar_id: str | None = None,
        send_updates: str = DEFAULT_SEND_UPDATES,
    ) -> dict[str, Any]:
        """
        Delete a Calendar event.
        """

        calendar = self._resolve_calendar_id(
            user_id=user_id,
            calendar_id=calendar_id,
        )

        normalized_event_id = (
            self._validate_identifier(
                event_id,
                "event_id",
            )
        )

        normalized_send_updates = (
            self._validate_send_updates(
                send_updates
            )
        )

        path = (
            f"/calendars/"
            f"{quote(calendar, safe='')}"
            "/events/"
            f"{quote(normalized_event_id, safe='')}"
        )

        self._request(
            user_id=user_id,
            method="DELETE",
            path=path,
            query=[
                (
                    "sendUpdates",
                    normalized_send_updates,
                )
            ],
        )

        return {
            "deleted": True,
            "event_id": normalized_event_id,
        }

    # =====================================================
    # HTTP BOUNDARY
    # =====================================================

    def _request(
        self,
        *,
        user_id: str,
        method: str,
        path: str,
        query: list[tuple[str, str]] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        access_token = (
            self.oauth_service
            .get_valid_access_token(
                user_id=user_id
            )
        )

        url = (
            self.BASE_URL
            + path
        )

        if query:
            url += (
                "?"
                + urlencode(
                    query,
                    doseq=True,
                )
            )

        headers = {
            "Authorization": (
                f"Bearer {access_token}"
            ),
            "Accept": "application/json",
        }

        encoded_body = None

        if body is not None:
            encoded_body = json.dumps(
                body
            ).encode(
                "utf-8"
            )
            headers[
                "Content-Type"
            ] = "application/json"

        request = Request(
            url=url,
            data=encoded_body,
            headers=headers,
            method=method,
        )

        try:
            with urlopen(
                request,
                timeout=self.HTTP_TIMEOUT_SECONDS,
            ) as response:
                raw = response.read()

        except HTTPError as exc:
            self._raise_http_error(
                exc
            )

        except (
            URLError,
            OSError,
        ) as exc:
            raise GoogleCalendarAPIError(
                "Google Calendar request could not be completed."
            ) from exc

        if not raw:
            return None

        try:
            decoded = json.loads(
                raw.decode(
                    "utf-8"
                )
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise GoogleCalendarAPIError(
                "Google Calendar returned an invalid response."
            ) from exc

        if not isinstance(
            decoded,
            dict,
        ):
            raise GoogleCalendarAPIError(
                "Google Calendar returned an invalid response."
            )

        return decoded

    @staticmethod
    def _raise_http_error(
        error: HTTPError,
    ) -> None:
        status_code = getattr(
            error,
            "code",
            None,
        )

        if status_code == 401:
            message = (
                "Google Calendar authorization is invalid or expired."
            )
        elif status_code == 403:
            message = (
                "Google Calendar access was denied."
            )
        elif status_code == 404:
            message = (
                "Google Calendar resource was not found."
            )
        elif status_code == 409:
            message = (
                "Google Calendar reported a resource conflict."
            )
        elif status_code == 429:
            message = (
                "Google Calendar rate limit was reached."
            )
        elif (
            isinstance(
                status_code,
                int,
            )
            and status_code >= 500
        ):
            message = (
                "Google Calendar is temporarily unavailable."
            )
        else:
            message = (
                "Google Calendar request was rejected."
            )

        raise GoogleCalendarAPIError(
            message,
            status_code=status_code,
        ) from error

    # =====================================================
    # VALIDATION / CONNECTION RESOLUTION
    # =====================================================

    def _resolve_calendar_id(
        self,
        *,
        user_id: str,
        calendar_id: str | None,
    ) -> str:
        normalized_user_id = (
            self._validate_identifier(
                user_id,
                "user_id",
            )
        )

        if calendar_id is not None:
            return self._validate_identifier(
                calendar_id,
                "calendar_id",
            )

        connection = (
            self.oauth_service.get_connection(
                user_id=normalized_user_id
            )
        )

        if connection is None:
            raise ValueError(
                "Google Calendar is not connected."
            )

        resolved = connection.get(
            "calendar_id"
        )

        return self._validate_identifier(
            resolved,
            "calendar_id",
        )

    @staticmethod
    def _validate_identifier(
        value: Any,
        field_name: str,
    ) -> str:
        if not isinstance(
            value,
            str,
        ):
            raise ValueError(
                f"{field_name} must be a string."
            )

        normalized = value.strip()

        if not normalized:
            raise ValueError(
                f"{field_name} cannot be empty."
            )

        return normalized

    @classmethod
    def _validate_send_updates(
        cls,
        value: Any,
    ) -> str:
        if not isinstance(
            value,
            str,
        ):
            raise ValueError(
                "send_updates must be a string."
            )

        normalized = value.strip()

        if normalized not in cls.VALID_SEND_UPDATES:
            raise ValueError(
                "send_updates must be one of: all, externalOnly, none."
            )

        return normalized

    @staticmethod
    def _validate_event_payload(
        event: Any,
        *,
        require_start_end: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(
            event,
            dict,
        ):
            raise ValueError(
                "Calendar event payload must be an object."
            )

        payload = dict(
            event
        )

        if require_start_end:
            if "start" not in payload:
                raise ValueError(
                    "Calendar event start is required."
                )

            if "end" not in payload:
                raise ValueError(
                    "Calendar event end is required."
                )

        for field_name in (
            "start",
            "end",
        ):
            if field_name in payload:
                value = payload[field_name]

                if not isinstance(
                    value,
                    dict,
                ):
                    raise ValueError(
                        f"Calendar event {field_name} must be an object."
                    )

                if not (
                    value.get(
                        "date"
                    )
                    or value.get(
                        "dateTime"
                    )
                ):
                    raise ValueError(
                        f"Calendar event {field_name} must contain date or dateTime."
                    )

        return payload

    @staticmethod
    def _format_datetime(
        value: datetime | str,
    ) -> str:
        if isinstance(
            value,
            datetime,
        ):
            if value.tzinfo is None:
                raise ValueError(
                    "Calendar datetime values must be timezone-aware."
                )

            return value.isoformat()

        if isinstance(
            value,
            str,
        ):
            normalized = value.strip()

            if not normalized:
                raise ValueError(
                    "Calendar datetime value cannot be empty."
                )

            return normalized

        raise ValueError(
            "Calendar datetime value must be a datetime or string."
        )
