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