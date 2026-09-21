from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SecuritySettings(BaseSettings):
    """
    API-facing security boundary configuration.

    Origins and trusted hosts are intentionally explicit. The default
    values are local-development safe and fail closed for deployment
    until real production values are supplied through the environment.
    """

    api_cors_allowed_origins: str = ""

    api_trusted_hosts: str = (
        "testserver,localhost,127.0.0.1"
    )

    security_hsts_enabled: bool = False

    security_hsts_max_age_seconds: int = Field(
        default=31536000,
        gt=0,
        le=63072000,
    )

    security_hsts_include_subdomains: bool = True

    security_hsts_preload: bool = False

    model_config = SettingsConfigDict(
        case_sensitive=False,
    )

    @field_validator(
        "api_cors_allowed_origins",
        "api_trusted_hosts",
    )
    @classmethod
    def _validate_security_list(
        cls,
        value: str,
    ) -> str:
        items = [
            item.strip()
            for item in str(value).split(",")
            if item.strip()
        ]

        if "*" in items:
            raise ValueError(
                "Wildcard '*' is not allowed for "
                "security configuration."
            )

        return str(value)

    @staticmethod
    def _parse_csv(
        value: str,
        field_name: str,
    ) -> tuple[str, ...]:
        items = tuple(
            item.strip()
            for item in str(value).split(",")
            if item.strip()
        )

        if "*" in items:
            raise ValueError(
                f"{field_name} cannot contain '*'."
            )

        return items

    def cors_allowed_origins(
        self,
    ) -> tuple[str, ...]:
        return self._parse_csv(
            self.api_cors_allowed_origins,
            "api_cors_allowed_origins",
        )

    def trusted_hosts(
        self,
    ) -> tuple[str, ...]:
        return self._parse_csv(
            self.api_trusted_hosts,
            "api_trusted_hosts",
        )


@lru_cache
def get_security_settings() -> SecuritySettings:
    """
    Return cached API security settings.

    This configuration is intentionally separate from the main
    application Settings model so security middleware does not depend
    on unrelated secrets being present at import time.
    """
    return SecuritySettings()



class RateLimitSettings(BaseSettings):
    """
    API rate limiting and quota configuration.

    Limits are environment-driven so deployment profiles can tune
    protection without changing application code.
    """

    api_rate_limit_enabled: bool = True

    api_rate_limit_requests_per_window: int = Field(
        default=120,
        ge=1,
        le=100000,
    )

    api_rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
    )

    api_auth_rate_limit_requests_per_window: int = Field(
        default=20,
        ge=1,
        le=100000,
    )

    api_auth_rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
    )

    model_config = SettingsConfigDict(
        case_sensitive=False,
    )


@lru_cache
def get_rate_limit_settings() -> RateLimitSettings:
    """
    Return cached API rate limit settings.
    """
    return RateLimitSettings()


class Settings(BaseSettings):
    """
    Application configuration loaded from environment variables.

    Sensitive values such as JWT signing secrets, SMTP
    credentials, Google OAuth credentials, and external-token
    encryption keys are intentionally never given insecure code
    defaults.
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

    integration_token_encryption_key: str | None = None

    calendar_google_client_id: str | None = None

    calendar_google_client_secret: str | None = None

    calendar_google_redirect_uri: str | None = None

    calendar_google_scopes: str = (
        "https://www.googleapis.com/auth/calendar.events"
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
