from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ConfirmationResponse(BaseModel):
    id: int
    conversation_id: int | None
    tool: str
    action: str
    data: dict[str, Any]
    reason: str
    status: str
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None


class ConfirmationExecutionResponse(BaseModel):
    confirmation: ConfirmationResponse
    success: bool
    status: str
    tool_result: dict[str, Any]
    workflow_result: dict[str, Any]
    error: str | None