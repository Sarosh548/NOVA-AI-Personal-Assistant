from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(
        default=None,
        max_length=200,
    )


class ConversationCreatedResponse(BaseModel):
    id: int


class ConversationResponse(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationMessageResponse(BaseModel):
    role: str
    content: str


class ConversationMessagesResponse(BaseModel):
    conversation_id: int
    messages: list[ConversationMessageResponse]


class ConversationStateResponse(BaseModel):
    conversation_id: int
    state: str
    last_role: str | None
    should_listen: bool


class ConversationUpdateRequest(BaseModel):
    title: str = Field(
        min_length=1,
        max_length=200,
    )


class ConversationUpdateResponse(BaseModel):
    updated: bool