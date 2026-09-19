from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class WorkflowStepResponse(BaseModel):
    id: int
    workflow_id: int
    step_id: str
    position: int
    tool: str
    action: str
    data: dict[str, Any]
    depends_on: list[str]
    status: str
    result: dict[str, Any] | None
    error: str | None
    attempts: int
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class WorkflowResponse(BaseModel):
    id: int
    conversation_id: int | None
    status: str
    execution_mode: str
    scheduled_at: datetime | None
    plan: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    steps: list[WorkflowStepResponse]


class WorkflowActionResponse(BaseModel):
    action: str
    updated: bool