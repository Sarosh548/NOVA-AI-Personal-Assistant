from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


MemoryCategory = Literal[
    "identity",
    "goal",
    "preference",
    "project",
    "interest",
    "context",
    "personal",
]

MemoryImportance = Literal[
    "high",
    "medium",
    "low",
]


class MemoryResponse(BaseModel):
    id: int
    memory: str = Field(min_length=1)
    category: MemoryCategory
    importance: MemoryImportance
    created_at: datetime
    updated_at: datetime


class MemoryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory: str = Field(
        min_length=1,
        max_length=10000,
    )
    category: MemoryCategory | None = None
    importance: MemoryImportance | None = None


class MemorySearchResponse(BaseModel):
    id: int
    memory: str = Field(min_length=1)
    category: MemoryCategory
    importance: MemoryImportance
    similarity: float = Field(ge=0.0, le=1.0)
    ranking_score: float
