from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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
