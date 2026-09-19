from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration loaded from environment variables.

    Sensitive values such as JWT signing secrets are intentionally
    not given insecure code defaults.
    """

    auth_jwt_secret_key: str = Field(
        min_length=32,
    )

    auth_jwt_algorithm: Literal["HS256"] = "HS256"

    auth_jwt_issuer: str = "nova-api"

    auth_jwt_audience: str = "nova-client"

    auth_access_token_expire_minutes: int = Field(
        default=10,
        gt=0,
        le=60,
    )

    model_config = SettingsConfigDict(
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    """
    Return the cached application settings.

    Environment variables are read only when settings are first
    requested, which keeps configuration injectable during tests.
    """
    return Settings()
