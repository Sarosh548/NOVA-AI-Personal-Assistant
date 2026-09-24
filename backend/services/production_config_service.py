from __future__ import annotations

import os
from urllib.parse import urlparse
from collections.abc import Mapping

from config import (
    RateLimitSettings,
    SecuritySettings,
    Settings,
    STTProviderSettings,
    TTSProviderSettings,
    get_rate_limit_settings,
    get_security_settings,
    get_settings,
    get_stt_provider_settings,
    get_tts_provider_settings,
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

KNOWN_INSECURE_PROVIDER_KEYS = {
    "test",
    "test-key",
    "ci-test-key",
}

KNOWN_INSECURE_WEB_SEARCH_KEYS = {
    "test",
    "test-key",
    "ci-test-key",
}

SUPPORTED_PRODUCTION_CALENDAR_SCOPES = {
    "https://www.googleapis.com/auth/calendar.events",
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
    stt_provider_settings: STTProviderSettings | None = None,
    tts_provider_settings: TTSProviderSettings | None = None,
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

    active_stt_provider_settings = (
        stt_provider_settings
        if stt_provider_settings is not None
        else get_stt_provider_settings()
    )

    active_tts_provider_settings = (
        tts_provider_settings
        if tts_provider_settings is not None
        else get_tts_provider_settings()
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

    tavily_api_key = str(
        source.get(
            "TAVILY_API_KEY",
            "",
        )
    ).strip()

    if not tavily_api_key:
        raise ProductionConfigurationError(
            "Production requires TAVILY_API_KEY."
        )

    if tavily_api_key.lower() in (
        value.lower()
        for value in KNOWN_INSECURE_WEB_SEARCH_KEYS
    ):
        raise ProductionConfigurationError(
            "Production TAVILY_API_KEY cannot "
            "use a development or CI placeholder."
        )

    deepgram_api_key = active_stt_provider_settings.deepgram_api_key

    if deepgram_api_key is None or not deepgram_api_key.strip():
        raise ProductionConfigurationError(
            "Production requires DEEPGRAM_API_KEY."
        )

    if deepgram_api_key.strip().lower() in {
        value.lower()
        for value in KNOWN_INSECURE_PROVIDER_KEYS
    }:
        raise ProductionConfigurationError(
            "Production DEEPGRAM_API_KEY cannot "
            "use a development or CI placeholder."
        )

    elevenlabs_api_key = active_tts_provider_settings.elevenlabs_api_key

    if elevenlabs_api_key is None or not elevenlabs_api_key.strip():
        raise ProductionConfigurationError(
            "Production requires ELEVENLABS_API_KEY."
        )

    if elevenlabs_api_key.strip().lower() in {
        value.lower()
        for value in KNOWN_INSECURE_PROVIDER_KEYS
    }:
        raise ProductionConfigurationError(
            "Production ELEVENLABS_API_KEY cannot "
            "use a development or CI placeholder."
        )

    elevenlabs_voice_id = active_tts_provider_settings.elevenlabs_voice_id

    if elevenlabs_voice_id is None or not elevenlabs_voice_id.strip():
        raise ProductionConfigurationError(
            "Production requires ELEVENLABS_VOICE_ID."
        )

    integration_encryption_key = active_settings.integration_token_encryption_key

    if integration_encryption_key is None or not integration_encryption_key.strip():
        raise ProductionConfigurationError(
            "Production requires INTEGRATION_TOKEN_ENCRYPTION_KEY."
        )

    from services.token_encryption_service import TokenEncryptionService

    try:
        TokenEncryptionService(integration_encryption_key)
    except ValueError as exc:
        raise ProductionConfigurationError(
            "Production INTEGRATION_TOKEN_ENCRYPTION_KEY is invalid."
        ) from exc

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

    notification_channel = str(
        active_settings.notification_default_channel
    ).strip().lower()

    if notification_channel == "console":
        raise ProductionConfigurationError(
            "Production requires an external notification channel; "
            "console is development-only."
        )

    if notification_channel == "webhook":
        webhook_url = str(
            active_settings.notification_webhook_url
            or ""
        ).strip()

        if not webhook_url:
            raise ProductionConfigurationError(
                "Production notification webhook requires "
                "NOTIFICATION_WEBHOOK_URL."
            )

        if not webhook_url.lower().startswith("https://"):
            raise ProductionConfigurationError(
                "Production notification webhook requires an HTTPS URL."
            )

    elif notification_channel == "email":
        smtp_host = str(
            active_settings.notification_smtp_host
            or ""
        ).strip()

        smtp_from = str(
            active_settings.notification_email_from_address
            or ""
        ).strip()

        if not smtp_host or not smtp_from:
            raise ProductionConfigurationError(
                "Production email notifications require "
                "NOTIFICATION_SMTP_HOST and "
                "NOTIFICATION_EMAIL_FROM_ADDRESS."
            )

        if (
            not active_settings.notification_smtp_starttls
            and not active_settings.notification_smtp_use_ssl
        ):
            raise ProductionConfigurationError(
                "Production email notifications require "
                "STARTTLS or SSL."
            )

    else:
        raise ProductionConfigurationError(
            "Production notification channel must be "
            "'email' or 'webhook'."
        )

    calendar_client_id = str(
        active_settings.calendar_google_client_id
        or ""
    ).strip()

    calendar_client_secret = str(
        active_settings.calendar_google_client_secret
        or ""
    ).strip()

    calendar_redirect_uri = str(
        active_settings.calendar_google_redirect_uri
        or ""
    ).strip()

    if not calendar_client_id:
        raise ProductionConfigurationError(
            "Production requires CALENDAR_GOOGLE_CLIENT_ID."
        )

    if not calendar_client_secret:
        raise ProductionConfigurationError(
            "Production requires CALENDAR_GOOGLE_CLIENT_SECRET."
        )

    if not calendar_redirect_uri:
        raise ProductionConfigurationError(
            "Production requires CALENDAR_GOOGLE_REDIRECT_URI."
        )

    parsed_calendar_redirect_uri = urlparse(
        calendar_redirect_uri
    )

    if parsed_calendar_redirect_uri.scheme != "https":
        raise ProductionConfigurationError(
            "Production CALENDAR_GOOGLE_REDIRECT_URI must use HTTPS."
        )

    redirect_host = (
        parsed_calendar_redirect_uri.hostname
        or ""
    ).strip().lower()

    if redirect_host in LOCAL_TRUSTED_HOSTS:
        raise ProductionConfigurationError(
            "Production CALENDAR_GOOGLE_REDIRECT_URI cannot "
            "use a local/test host."
        )

    calendar_scopes = " ".join(
        str(
            active_settings.calendar_google_scopes
            or ""
        ).split()
    )

    if not calendar_scopes:
        raise ProductionConfigurationError(
            "Production requires CALENDAR_GOOGLE_SCOPES."
        )

    configured_calendar_scopes = set(
        calendar_scopes.split()
    )

    if configured_calendar_scopes != (
        SUPPORTED_PRODUCTION_CALENDAR_SCOPES
    ):
        raise ProductionConfigurationError(
            "Production CALENDAR_GOOGLE_SCOPES must "
            "use only the supported least-privilege "
            "Calendar scope."
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