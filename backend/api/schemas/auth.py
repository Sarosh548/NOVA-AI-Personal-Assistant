from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    """
    Request body for local NOVA account registration.
    """

    identifier: str = Field(
        min_length=1,
        max_length=255,
    )

    password: str = Field(
        min_length=8,
        max_length=256,
    )

    display_name: str | None = Field(
        default=None,
        max_length=200,
    )


class RefreshRequest(BaseModel):
    """
    Request body for refresh-token rotation.
    """

    refresh_token: str = Field(
        min_length=1,
    )


class UserResponse(BaseModel):
    """
    Safe public representation of the canonical NOVA user.

    Authentication credentials and provider information are
    intentionally never exposed here.
    """

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: str
    display_name: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TokenResponse(BaseModel):
    """
    Authentication response containing the short-lived access
    token and the newly issued refresh token.
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    session_id: str
    user: UserResponse
