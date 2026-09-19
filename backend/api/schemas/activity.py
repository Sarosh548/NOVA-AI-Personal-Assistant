from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ActivityEventResponse(BaseModel):
    id: int
    conversation_id: int | None
    workflow_id: int | None
    event_type: str
    source: str
    status: str
    title: str
    summary: str
    metadata: dict[str, Any]
    created_at: datetime