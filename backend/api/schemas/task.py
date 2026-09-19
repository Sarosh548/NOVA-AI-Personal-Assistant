from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TaskCreateRequest(BaseModel):
    title: str = Field(
        min_length=1,
        max_length=300,
    )
    description: str | None = None
    priority: str = "medium"
    due_at: datetime | None = None


class TaskCreatedResponse(BaseModel):
    id: int


class TaskResponse(BaseModel):
    id: int
    title: str
    description: str | None
    status: str
    priority: str
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskUpdateRequest(BaseModel):
    priority: str | None = None
    due_at: datetime | None = None


class TaskUpdateResponse(BaseModel):
    updated: bool


class TaskActionResponse(BaseModel):
    action: str
    updated: bool