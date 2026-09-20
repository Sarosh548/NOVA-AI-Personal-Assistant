from __future__ import annotations

from datetime import date as Date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CalendarAuthorizationUrlResponse(BaseModel):
    authorization_url: str


class CalendarConnectionResponse(BaseModel):
    id: str
    user_id: str
    provider: str
    calendar_id: str
    scopes: str
    token_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CalendarConnectionStatusResponse(BaseModel):
    connected: bool
    connection: CalendarConnectionResponse | None


class CalendarEventBoundaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: Date | None = None
    dateTime: datetime | None = None
    timeZone: str | None = None

    @model_validator(mode="after")
    def validate_boundary(self):
        if (
            (self.date is None)
            == (self.dateTime is None)
        ):
            raise ValueError(
                "Exactly one of date or dateTime is required."
            )

        if self.dateTime is not None:
            if (
                self.dateTime.tzinfo is None
                or self.dateTime.utcoffset() is None
            ):
                raise ValueError(
                    "dateTime must include a timezone offset."
                )

        if self.timeZone is not None and not self.timeZone.strip():
            raise ValueError(
                "timeZone cannot be empty."
            )

        return self


class CalendarAttendeeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    displayName: str | None = None
    optional: bool | None = None
    resource: bool | None = None


class CalendarEventCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str | None = None
    description: str | None = None
    location: str | None = None
    start: CalendarEventBoundaryRequest
    end: CalendarEventBoundaryRequest
    attendees: list[CalendarAttendeeRequest] | None = None

    @model_validator(mode="after")
    def validate_time_boundary(self):
        if (
            self.start.dateTime is not None
            and self.end.dateTime is not None
            and self.end.dateTime <= self.start.dateTime
        ):
            raise ValueError(
                "end must be after start."
            )

        if (
            self.start.date is not None
            and self.end.date is not None
            and self.end.date <= self.start.date
        ):
            raise ValueError(
                "end must be after start."
            )

        if (
            self.start.date is not None
            and self.end.dateTime is not None
        ) or (
            self.start.dateTime is not None
            and self.end.date is not None
        ):
            raise ValueError(
                "start and end must use the same date or dateTime format."
            )

        return self


class CalendarEventUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str | None = None
    description: str | None = None
    location: str | None = None
    start: CalendarEventBoundaryRequest | None = None
    end: CalendarEventBoundaryRequest | None = None
    attendees: list[CalendarAttendeeRequest] | None = None

    @model_validator(mode="after")
    def validate_time_boundary(self):
        if (
            self.start is None
        ) != (
            self.end is None
        ):
            raise ValueError(
                "start and end must be provided together."
            )

        if (
            self.start is not None
            and self.end is not None
        ):
            if (
                self.start.dateTime is not None
                and self.end.dateTime is not None
                and self.end.dateTime <= self.start.dateTime
            ):
                raise ValueError(
                    "end must be after start."
                )

            if (
                self.start.date is not None
                and self.end.date is not None
                and self.end.date <= self.start.date
            ):
                raise ValueError(
                    "end must be after start."
                )

            if (
                self.start.date is not None
                and self.end.dateTime is not None
            ) or (
                self.start.dateTime is not None
                and self.end.date is not None
            ):
                raise ValueError(
                    "start and end must use the same date or dateTime format."
                )

        if all(
            value is None
            for value in (
                self.summary,
                self.description,
                self.location,
                self.start,
                self.end,
                self.attendees,
            )
        ):
            raise ValueError(
                "Calendar event update cannot be empty."
            )

        return self


class CalendarEventListResponse(BaseModel):
    events: list[dict[str, Any]]
    next_page_token: str | None = None
    next_sync_token: str | None = None


class CalendarEventDeleteResponse(BaseModel):
    deleted: bool
    event_id: str


CalendarSendUpdates = Literal[
    "all",
    "externalOnly",
    "none",
]


class CalendarErrorResponse(BaseModel):
    detail: str
