from __future__ import annotations

import os
from collections.abc import Mapping

from config import (
    RateLimitSettings,
    SecuritySettings,
    Settings,
    get_rate_limit_settings,
    get_security_settings,
    get_settings,
)


SUPPORTED_ENVIRONMENTS = {
    "development",
    "test",
    "production",
}

LOCAL_TRUSTED_HOSTS = {
    "testserver",
    "localhost",
    "127.0.0.1",
    "::1",
}

KNOWN_INSECURE_JWT_SECRETS = {
    "change-me",
    "change-me-please",
    "local-test-auth-jwt-secret-key-32-characters",
    "ci-test-auth-jwt-secret-key-32-characters-min",
}

KNOWN_INSECURE_GROQ_KEYS = {
    "test",
    "test-key",
    "ci-test-key",
}


class ProductionConfigurationError(
    RuntimeError
):
    """Raised when runtime configuration is unsafe for production."""


def _environment(
    environ: Mapping[str, str] | None = None,
) -> str:
    source = (
        environ
        if environ is not None
        else os.environ
    )

    value = str(
        source.get(
            "NOVA_ENV",
            "development",
        )
    ).strip().lower()

    if value not in SUPPORTED_ENVIRONMENTS:
        raise ProductionConfigurationError(
            "NOVA_ENV must be one of: "
            "development, test, production."
        )

    return value


def validate_runtime_configuration(
    *,
    settings: Settings | None = None,
    security_settings: SecuritySettings | None = None,
    rate_limit_settings: RateLimitSettings | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """
    Validate NOVA runtime configuration.

    Development and test environments keep the existing flexible
    defaults. Production requires explicit security and provider
    configuration so local/test settings cannot silently ship.
    """

    source = (
        environ
        if environ is not None
        else os.environ
    )

    environment = _environment(
        source
    )

    if environment != "production":
        return environment

    active_settings = (
        settings
        if settings is not None
        else get_settings()
    )

    active_security_settings = (
        security_settings
        if security_settings is not None
        else get_security_settings()
    )

    active_rate_limit_settings = (
        rate_limit_settings
        if rate_limit_settings is not None
        else get_rate_limit_settings()
    )

    if (
        not active_security_settings
        .security_hsts_enabled
    ):
        raise ProductionConfigurationError(
            "Production requires SECURITY_HSTS_ENABLED=true."
        )

    trusted_hosts = (
        active_security_settings
        .trusted_hosts()
    )

    if not trusted_hosts:
        raise ProductionConfigurationError(
            "Production requires at least one trusted host."
        )

    local_hosts = {
        host.strip().lower()
        for host in trusted_hosts
        if host.strip()
    }

    unsafe_local_hosts = sorted(
        local_hosts.intersection(
            LOCAL_TRUSTED_HOSTS
        )
    )

    if unsafe_local_hosts:
        raise ProductionConfigurationError(
            "Production API_TRUSTED_HOSTS cannot "
            "contain local/test hosts: "
            + ", ".join(
                unsafe_local_hosts
            )
            + "."
        )

    jwt_secret = (
        active_settings
        .auth_jwt_secret_key
        .strip()
    )

    if jwt_secret.lower() in {
        value.lower()
        for value in KNOWN_INSECURE_JWT_SECRETS
    }:
        raise ProductionConfigurationError(
            "Production AUTH_JWT_SECRET_KEY cannot "
            "use a development or CI placeholder."
        )

    groq_api_key = str(
        source.get(
            "GROQ_API_KEY",
            "",
        )
    ).strip()

    if not groq_api_key:
        raise ProductionConfigurationError(
            "Production requires GROQ_API_KEY."
        )

    if groq_api_key.lower() in (
        value.lower()
        for value in KNOWN_INSECURE_GROQ_KEYS
    ):
        raise ProductionConfigurationError(
            "Production GROQ_API_KEY cannot "
            "use a development or CI placeholder."
        )

    database_url = str(
        source.get(
            "DATABASE_URL",
            "",
        )
    ).strip()

    if not database_url:
        raise ProductionConfigurationError(
            "Production requires DATABASE_URL."
        )

    if (
        not active_rate_limit_settings
        .api_rate_limit_enabled
    ):
        raise ProductionConfigurationError(
            "Production API rate limiting "
            "cannot be disabled."
        )

    if (
        not active_rate_limit_settings
        .voice_rate_limit_enabled
    ):
        raise ProductionConfigurationError(
            "Production voice rate limiting "
            "cannot be disabled."
        )

    return environment