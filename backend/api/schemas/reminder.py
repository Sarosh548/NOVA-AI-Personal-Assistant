from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReminderCreateRequest(BaseModel):
    title: str = Field(
        min_length=1,
        max_length=300,
    )
    reminder_time: datetime


class ReminderCreatedResponse(BaseModel):
    id: int


class ReminderResponse(BaseModel):
    id: int
    title: str
    reminder_time: datetime
    status: str


class ReminderUpdateRequest(BaseModel):
    title: str | None = Field(
        default=None,
        max_length=300,
    )
    reminder_time: datetime | None = None


class ReminderUpdateResponse(BaseModel):
    updated: bool


class ReminderActionResponse(BaseModel):
    action: str
    updated: bool