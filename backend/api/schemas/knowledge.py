from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDocumentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        min_length=1,
        max_length=300,
    )

    content: str = Field(
        min_length=1,
        max_length=250_000,
    )

    source: str | None = Field(
        default=None,
        max_length=1000,
    )


class KnowledgeUrlCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(
        min_length=1,
        max_length=2048,
    )


class KnowledgeDocumentResponse(BaseModel):
    id: int
    title: str
    source: str | None
    chunk_count: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentDetailResponse(
    KnowledgeDocumentResponse
):
    content: str = Field(min_length=1)


class KnowledgeSearchResponse(BaseModel):
    document_id: int
    title: str
    source: str | None
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    similarity: float = Field(
        ge=0.0,
        le=1.0,
    )
