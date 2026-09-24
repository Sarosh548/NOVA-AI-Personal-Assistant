from __future__ import annotations

import pytest

from config import (
    RateLimitSettings,
    SecuritySettings,
    Settings,
    STTProviderSettings,
    TTSProviderSettings,
)
from services.production_config_service import (
    ProductionConfigurationError,
    validate_runtime_configuration,
)


def _settings() -> Settings:
    return Settings(
        auth_jwt_secret_key=(
            "production-secret-value-that-is"
            "-longer-than-thirty-two-characters"
        ),
    )


def _security_settings() -> SecuritySettings:
    return SecuritySettings(
        api_trusted_hosts="api.example.com",
        security_hsts_enabled=True,
    )


def _rate_limit_settings() -> RateLimitSettings:
    return RateLimitSettings(
        api_rate_limit_enabled=True,
        voice_rate_limit_enabled=True,
    )


def _stt_provider_settings() -> STTProviderSettings:
    return STTProviderSettings(
        deepgram_api_key="deepgram-production-key",
    )


def _tts_provider_settings() -> TTSProviderSettings:
    return TTSProviderSettings(
        elevenlabs_api_key="elevenlabs-production-key",
        elevenlabs_voice_id="production-voice",
    )


def _production_settings() -> Settings:
    return Settings(
        auth_jwt_secret_key=(
            "production-secret-value-that-is"
            "-longer-than-thirty-two-characters"
        ),
        integration_token_encryption_key=(
            "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
        ),
        notification_default_channel="webhook",
        notification_webhook_url=(
            "https://notify.example.com/nova"
        ),
        calendar_google_client_id="google-production-client",
        calendar_google_client_secret="google-production-secret",
        calendar_google_redirect_uri=(
            "https://api.example.com/integrations/google/calendar/callback"
        ),
        calendar_google_scopes=(
            "https://www.googleapis.com/auth/calendar.events"
        ),
    )


def _production_environment() -> dict[str, str]:
    return {
        "NOVA_ENV": "production",
        "DATABASE_URL": (
            "postgresql+psycopg://user:password@db:5432/nova_db"
        ),
        "GROQ_API_KEY": "real-production-key",
        "TAVILY_API_KEY": "real-web-search-production-key",
    }


def test_development_environment_keeps_existing_flexible_defaults():
    environment = validate_runtime_configuration(
        environ={
            "NOVA_ENV": "development",
        }
    )

    assert environment == "development"


def test_test_environment_keeps_existing_flexible_defaults():
    environment = validate_runtime_configuration(
        environ={
            "NOVA_ENV": "test",
        }
    )

    assert environment == "test"


def test_production_accepts_explicit_secure_configuration():
    environment = validate_runtime_configuration(
        settings=_production_settings(),
        security_settings=_security_settings(),
        rate_limit_settings=_rate_limit_settings(),
        stt_provider_settings=_stt_provider_settings(),
        tts_provider_settings=_tts_provider_settings(),
        environ=_production_environment(),
    )

    assert environment == "production"


def test_unknown_environment_is_rejected():
    with pytest.raises(
        ProductionConfigurationError,
        match="NOVA_ENV must be one of",
    ):
        validate_runtime_configuration(
            environ={
                "NOVA_ENV": "staging",
            }
        )


def test_production_requires_hsts():
    security_settings = SecuritySettings(
        api_trusted_hosts="api.example.com",
        security_hsts_enabled=False,
    )

    with pytest.raises(
        ProductionConfigurationError,
        match="SECURITY_HSTS_ENABLED",
    ):
        validate_runtime_configuration(
            settings=_settings(),
            security_settings=security_settings,
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=_production_environment(),
        )


def test_production_rejects_local_trusted_hosts():
    security_settings = SecuritySettings(
        api_trusted_hosts="localhost,api.example.com",
        security_hsts_enabled=True,
    )

    with pytest.raises(
        ProductionConfigurationError,
        match="local/test hosts",
    ):
        validate_runtime_configuration(
            settings=_settings(),
            security_settings=security_settings,
            rate_limit_settings=_rate_limit_settings(),
            environ=_production_environment(),
        )


def test_production_requires_groq_api_key():
    environ = _production_environment()
    del environ["GROQ_API_KEY"]

    with pytest.raises(
        ProductionConfigurationError,
        match="GROQ_API_KEY",
    ):
        validate_runtime_configuration(
            settings=_production_settings(),
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=environ,
        )


def test_production_requires_tavily_api_key():
    environ = _production_environment()
    del environ["TAVILY_API_KEY"]

    with pytest.raises(
        ProductionConfigurationError,
        match="TAVILY_API_KEY",
    ):
        validate_runtime_configuration(
            settings=_production_settings(),
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=environ,
        )


def test_production_rejects_ci_tavily_placeholder():
    environ = _production_environment()
    environ["TAVILY_API_KEY"] = "ci-test-key"

    with pytest.raises(
        ProductionConfigurationError,
        match="TAVILY_API_KEY",
    ):
        validate_runtime_configuration(
            settings=_production_settings(),
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=environ,
        )


def test_production_rejects_ci_groq_placeholder():
    environ = _production_environment()
    environ["GROQ_API_KEY"] = "ci-test-key"

    with pytest.raises(
        ProductionConfigurationError,
        match="CI placeholder",
    ):
        validate_runtime_configuration(
            settings=_production_settings(),
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=environ,
        )


def test_production_requires_database_url():
    environ = _production_environment()
    del environ["DATABASE_URL"]

    with pytest.raises(
        ProductionConfigurationError,
        match="DATABASE_URL",
    ):
        validate_runtime_configuration(
            settings=_production_settings(),
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=environ,
        )


def test_production_rejects_insecure_jwt_placeholder():
    settings = Settings(
        auth_jwt_secret_key=(
            "local-test-auth-jwt-secret-key-32-characters"
        )
    )

    with pytest.raises(
        ProductionConfigurationError,
        match="AUTH_JWT_SECRET_KEY",
    ):
        validate_runtime_configuration(
            settings=settings,
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            environ=_production_environment(),
        )


def test_production_rejects_console_notification_channel():
    settings = _production_settings()
    settings.notification_default_channel = "console"

    with pytest.raises(
        ProductionConfigurationError,
        match="external notification channel",
    ):
        validate_runtime_configuration(
            settings=settings,
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=_production_environment(),
        )


def test_production_requires_webhook_notification_url():
    settings = _production_settings()
    settings.notification_webhook_url = None

    with pytest.raises(
        ProductionConfigurationError,
        match="NOTIFICATION_WEBHOOK_URL",
    ):
        validate_runtime_configuration(
            settings=settings,
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=_production_environment(),
        )


def test_production_requires_https_webhook_notification_url():
    settings = _production_settings()
    settings.notification_webhook_url = (
        "http://notify.example.com/nova"
    )

    with pytest.raises(
        ProductionConfigurationError,
        match="HTTPS",
    ):
        validate_runtime_configuration(
            settings=settings,
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=_production_environment(),
        )


def test_production_accepts_secure_email_notification_configuration():
    settings = _production_settings()
    settings.notification_default_channel = "email"
    settings.notification_webhook_url = None
    settings.notification_smtp_host = "smtp.example.com"
    settings.notification_email_from_address = "nova@example.com"
    settings.notification_smtp_starttls = True
    settings.notification_smtp_use_ssl = False

    environment = validate_runtime_configuration(
        settings=settings,
        security_settings=_security_settings(),
        rate_limit_settings=_rate_limit_settings(),
        stt_provider_settings=_stt_provider_settings(),
        tts_provider_settings=_tts_provider_settings(),
        environ=_production_environment(),
    )

    assert environment == "production"


def test_production_requires_google_calendar_client_id():
    settings = _production_settings()
    settings.calendar_google_client_id = None

    with pytest.raises(
        ProductionConfigurationError,
        match="CALENDAR_GOOGLE_CLIENT_ID",
    ):
        validate_runtime_configuration(
            settings=settings,
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=_production_environment(),
        )


def test_production_requires_google_calendar_client_secret():
    settings = _production_settings()
    settings.calendar_google_client_secret = None

    with pytest.raises(
        ProductionConfigurationError,
        match="CALENDAR_GOOGLE_CLIENT_SECRET",
    ):
        validate_runtime_configuration(
            settings=settings,
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=_production_environment(),
        )


def test_production_requires_google_calendar_redirect_uri():
    settings = _production_settings()
    settings.calendar_google_redirect_uri = None

    with pytest.raises(
        ProductionConfigurationError,
        match="CALENDAR_GOOGLE_REDIRECT_URI",
    ):
        validate_runtime_configuration(
            settings=settings,
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=_production_environment(),
        )


def test_production_requires_https_google_calendar_redirect_uri():
    settings = _production_settings()
    settings.calendar_google_redirect_uri = (
        "http://api.example.com/integrations/google/calendar/callback"
    )

    with pytest.raises(
        ProductionConfigurationError,
        match="HTTPS",
    ):
        validate_runtime_configuration(
            settings=settings,
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=_production_environment(),
        )


def test_production_rejects_local_google_calendar_redirect_uri():
    settings = _production_settings()
    settings.calendar_google_redirect_uri = (
        "https://localhost/integrations/google/calendar/callback"
    )

    with pytest.raises(
        ProductionConfigurationError,
        match="local/test host",
    ):
        validate_runtime_configuration(
            settings=settings,
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=_production_environment(),
        )


def test_production_accepts_supported_google_calendar_scope():
    settings = _production_settings(
        calendar_google_scopes=(
            "  https://www.googleapis.com/auth/calendar.events  "
        )
    )

    assert (
        validate_runtime_configuration(
            settings=settings,
            environ=_production_environment(),
        )
        == "production"
    )


def test_production_rejects_unsupported_google_calendar_scope():
    settings = _production_settings(
        calendar_google_scopes=(
            "https://www.googleapis.com/auth/calendar"
        )
    )

    with pytest.raises(
        ProductionConfigurationError,
        match="supported least-privilege",
    ):
        validate_runtime_configuration(
            settings=settings,
            environ=_production_environment(),
        )


def test_production_requires_google_calendar_scopes():
    settings = _production_settings()
    settings.calendar_google_scopes = ""

    with pytest.raises(
        ProductionConfigurationError,
        match="CALENDAR_GOOGLE_SCOPES",
    ):
        validate_runtime_configuration(
            settings=settings,
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=_production_environment(),
        )


def test_production_requires_api_rate_limiting():
    rate_limit_settings = RateLimitSettings(
        api_rate_limit_enabled=False,
        voice_rate_limit_enabled=True,
    )

    with pytest.raises(
        ProductionConfigurationError,
        match="API rate limiting",
    ):
        validate_runtime_configuration(
            settings=_production_settings(),
            security_settings=_security_settings(),
            rate_limit_settings=rate_limit_settings,
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=_production_environment(),
        )


def test_production_requires_deepgram_api_key():
    stt_settings = STTProviderSettings(
        deepgram_api_key=None,
    )

    with pytest.raises(
        ProductionConfigurationError,
        match="DEEPGRAM_API_KEY",
    ):
        validate_runtime_configuration(
            settings=_production_settings(),
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=stt_settings,
            tts_provider_settings=_tts_provider_settings(),
            environ=_production_environment(),
        )


def test_production_rejects_ci_deepgram_placeholder():
    stt_settings = STTProviderSettings(
        deepgram_api_key="ci-test-key",
    )

    with pytest.raises(
        ProductionConfigurationError,
        match="DEEPGRAM_API_KEY",
    ):
        validate_runtime_configuration(
            settings=_production_settings(),
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=stt_settings,
            tts_provider_settings=_tts_provider_settings(),
            environ=_production_environment(),
        )


def test_production_requires_elevenlabs_api_key():
    tts_settings = TTSProviderSettings(
        elevenlabs_api_key=None,
        elevenlabs_voice_id="production-voice",
    )

    with pytest.raises(
        ProductionConfigurationError,
        match="ELEVENLABS_API_KEY",
    ):
        validate_runtime_configuration(
            settings=_production_settings(),
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=tts_settings,
            environ=_production_environment(),
        )


def test_production_requires_elevenlabs_voice_id():
    tts_settings = TTSProviderSettings(
        elevenlabs_api_key="elevenlabs-production-key",
        elevenlabs_voice_id=None,
    )

    with pytest.raises(
        ProductionConfigurationError,
        match="ELEVENLABS_VOICE_ID",
    ):
        validate_runtime_configuration(
            settings=_production_settings(),
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=tts_settings,
            environ=_production_environment(),
        )


def test_production_requires_integration_token_encryption_key():
    settings = Settings(
        auth_jwt_secret_key=(
            "production-secret-value-that-is"
            "-longer-than-thirty-two-characters"
        ),
        integration_token_encryption_key=None,
    )

    with pytest.raises(
        ProductionConfigurationError,
        match="INTEGRATION_TOKEN_ENCRYPTION_KEY",
    ):
        validate_runtime_configuration(
            settings=settings,
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=_production_environment(),
        )


def test_production_rejects_invalid_integration_token_encryption_key():
    settings = Settings(
        auth_jwt_secret_key=(
            "production-secret-value-that-is"
            "-longer-than-thirty-two-characters"
        ),
        integration_token_encryption_key="not-a-fernet-key",
    )

    with pytest.raises(
        ProductionConfigurationError,
        match="INTEGRATION_TOKEN_ENCRYPTION_KEY is invalid",
    ):
        validate_runtime_configuration(
            settings=settings,
            security_settings=_security_settings(),
            rate_limit_settings=_rate_limit_settings(),
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=_production_environment(),
        )



def test_production_requires_voice_rate_limiting():
    rate_limit_settings = RateLimitSettings(
        api_rate_limit_enabled=True,
        voice_rate_limit_enabled=False,
    )

    with pytest.raises(
        ProductionConfigurationError,
        match="voice rate limiting",
    ):
        validate_runtime_configuration(
            settings=_production_settings(),
            security_settings=_security_settings(),
            rate_limit_settings=rate_limit_settings,
            stt_provider_settings=_stt_provider_settings(),
            tts_provider_settings=_tts_provider_settings(),
            environ=_production_environment(),
        )