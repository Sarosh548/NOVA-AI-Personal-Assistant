from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration loaded from environment variables.

    Sensitive values such as JWT signing secrets and SMTP
    credentials are intentionally never given insecure code defaults.
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

    notification_default_channel: str = Field(
        default="console",
        min_length=1,
        max_length=50,
    )

    notification_webhook_url: str | None = None

    notification_webhook_secret: str | None = None

    notification_webhook_timeout_seconds: int = Field(
        default=10,
        gt=0,
        le=60,
    )

    notification_smtp_host: str | None = None

    notification_smtp_port: int = Field(
        default=587,
        gt=0,
        le=65535,
    )

    notification_smtp_username: str | None = None

    notification_smtp_password: str | None = None

    notification_email_from_address: str | None = None

    notification_smtp_starttls: bool = True

    notification_smtp_use_ssl: bool = False

    notification_smtp_timeout_seconds: int = Field(
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