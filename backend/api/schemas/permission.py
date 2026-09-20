from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PermissionMode = Literal[
    "allow",
    "confirm",
    "deny",
]

PermissionAction = Literal[
    "list",
    "get",
    "search",
    "send",
    "create",
    "update",
    "start",
    "complete",
    "cancel",
    "delete",
]


class PermissionSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: PermissionMode


class PermissionResponse(BaseModel):
    id: int
    tool: str = Field(min_length=1, max_length=100)
    action: PermissionAction
    mode: PermissionMode
    created_at: datetime
    updated_at: datetime
