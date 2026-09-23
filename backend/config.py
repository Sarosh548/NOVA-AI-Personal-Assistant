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

    api_max_request_body_bytes: int = Field(
        default=10_485_760,
        ge=1024,
        le=52_428_800,
    )

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

    voice_rate_limit_enabled: bool = True

    voice_turn_start_requests_per_window: int = Field(
        default=30,
        ge=1,
        le=100000,
    )

    voice_turn_start_window_seconds: int = Field(
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


class VoiceSettings(BaseSettings):
    """
    Realtime voice transport and bounded session limits.

    These settings protect the WebSocket boundary while keeping
    the transport suitable for low-latency binary audio streaming.
    """

    voice_control_message_max_bytes: int = Field(
        default=16_384,
        ge=1024,
        le=1_048_576,
    )

    voice_audio_frame_max_bytes: int = Field(
        default=65_536,
        ge=1024,
        le=1_048_576,
    )

    voice_stt_finalization_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        le=30,
    )

    voice_default_audio_encoding: str = Field(
        default="pcm_s16le",
        min_length=1,
        max_length=64,
    )

    voice_default_sample_rate_hz: int = Field(
        default=16_000,
        ge=8_000,
        le=192_000,
    )

    voice_default_channels: int = Field(
        default=1,
        ge=1,
        le=8,
    )

    voice_stt_event_queue_max_items: int = Field(
        default=64,
        ge=1,
        le=4096,
    )

    voice_turn_audio_max_bytes: int = Field(
        default=10_485_760,
        ge=65_536,
        le=52_428_800,
    )

    voice_turn_max_frames: int = Field(
        default=4096,
        ge=1,
        le=100_000,
    )

    voice_session_idle_timeout_seconds: int = Field(
        default=300,
        ge=10,
        le=3600,
    )

    voice_authentication_timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=60,
    )

    voice_session_max_duration_seconds: int = Field(
        default=1800,
        ge=60,
        le=86400,
    )

    voice_session_lease_duration_seconds: int = Field(
        default=360,
        ge=60,
        le=86400,
    )

    voice_session_lease_heartbeat_interval_seconds: int = Field(
        default=30,
        ge=5,
        le=3600,
    )

    voice_turn_max_duration_seconds: int = Field(
        default=120,
        ge=1,
        le=900,
    )

    voice_tts_output_encoding: str = Field(
        default="pcm_s16le",
        min_length=1,
        max_length=64,
    )

    voice_tts_output_sample_rate_hz: int = Field(
        default=16_000,
        ge=8_000,
        le=192_000,
    )

    voice_tts_output_channels: int = Field(
        default=1,
        ge=1,
        le=8,
    )

    voice_tts_audio_chunk_max_bytes: int = Field(
        default=65_536,
        ge=1_024,
        le=1_048_576,
    )

    voice_tts_event_queue_max_items: int = Field(
        default=64,
        ge=1,
        le=4_096,
    )

    voice_response_delta_queue_max_items: int = Field(
        default=64,
        ge=1,
        le=4_096,
    )

    voice_response_delta_enqueue_timeout_seconds: float = Field(
        default=2.0,
        gt=0,
        le=30,
    )

    model_config = SettingsConfigDict(
        case_sensitive=False,
    )


@lru_cache
def get_voice_settings() -> VoiceSettings:
    """
    Return cached realtime voice settings.
    """
    return VoiceSettings()


class STTProviderSettings(BaseSettings):
    """
    Concrete realtime STT provider configuration.

    Provider credentials remain environment-driven and are never placed
    in WebSocket URLs or application logs.
    """

    deepgram_api_key: str | None = Field(
        default=None,
        min_length=1,
    )

    deepgram_ws_url: str = (
        "wss://api.deepgram.com/v1/listen"
    )

    deepgram_model: str = "nova-3"

    deepgram_language: str = "en-US"

    deepgram_interim_results: bool = True

    # 700 ms limits accidental early turn cuts while remaining responsive.
    # Keep this environment-tunable; later latency/segmentation telemetry
    # should drive any further tuning.
    deepgram_endpointing_ms: int = Field(
        default=700,
        ge=50,
        le=5000,
    )

    # Deepgram requires at least 1000 ms for useful UtteranceEnd behavior
    # with its typical interim-result cadence.
    deepgram_utterance_end_ms: int = Field(
        default=1200,
        ge=1000,
        le=5000,
    )

    deepgram_vad_events: bool = True

    deepgram_smart_format: bool = True

    deepgram_no_delay: bool = False

    stt_connect_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=60,
    )

    stt_connect_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
    )

    stt_connect_retry_backoff_seconds: float = Field(
        default=0.25,
        gt=0,
        le=5,
    )

    stt_ping_interval_seconds: float = Field(
        default=20.0,
        gt=0,
        le=300,
    )

    stt_ping_timeout_seconds: float = Field(
        default=20.0,
        gt=0,
        le=300,
    )

    stt_close_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=60,
    )

    stt_provider_max_message_bytes: int = Field(
        default=1_048_576,
        ge=16_384,
        le=10_485_760,
    )

    stt_provider_max_queue_items: int = Field(
        default=16,
        ge=1,
        le=1024,
    )

    stt_event_queue_max_items: int = Field(
        default=64,
        ge=1,
        le=4096,
    )

    model_config = SettingsConfigDict(
        case_sensitive=False,
    )


@lru_cache
def get_stt_provider_settings() -> STTProviderSettings:
    """
    Return cached concrete STT provider settings.
    """
    return STTProviderSettings()


class TTSProviderSettings(BaseSettings):
    """
    Concrete realtime TTS provider configuration.

    Provider credentials remain environment-driven and are never placed
    in WebSocket URLs or application logs.
    """

    elevenlabs_api_key: str | None = Field(
        default=None,
        min_length=1,
    )

    elevenlabs_voice_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    elevenlabs_ws_url: str = (
        "wss://api.elevenlabs.io/v1/text-to-speech"
    )

    elevenlabs_model: str = "eleven_flash_v2_5"

    elevenlabs_stability: float = Field(
        default=0.5,
        ge=0,
        le=1,
    )

    elevenlabs_similarity_boost: float = Field(
        default=0.8,
        ge=0,
        le=1,
    )

    elevenlabs_speed: float = Field(
        default=1.0,
        gt=0,
        le=2,
    )

    elevenlabs_use_speaker_boost: bool = False

    elevenlabs_chunk_length_schedule: str = (
        "120,160,250,290"
    )

    tts_connect_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=60,
    )

    tts_connect_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
    )

    tts_connect_retry_backoff_seconds: float = Field(
        default=0.25,
        gt=0,
        le=5,
    )

    tts_ping_interval_seconds: float = Field(
        default=20.0,
        gt=0,
        le=300,
    )

    tts_ping_timeout_seconds: float = Field(
        default=20.0,
        gt=0,
        le=300,
    )

    tts_close_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=60,
    )

    tts_provider_max_message_bytes: int = Field(
        default=1_048_576,
        ge=16_384,
        le=10_485_760,
    )

    tts_provider_max_queue_items: int = Field(
        default=16,
        ge=1,
        le=1024,
    )

    tts_event_queue_max_items: int = Field(
        default=64,
        ge=1,
        le=4096,
    )

    model_config = SettingsConfigDict(
        case_sensitive=False,
    )

    def chunk_length_schedule(self) -> tuple[int, ...]:
        values = tuple(
            int(item.strip())
            for item in str(
                self.elevenlabs_chunk_length_schedule
            ).split(",")
            if item.strip()
        )

        if not values:
            raise ValueError(
                "elevenlabs_chunk_length_schedule cannot be empty."
            )

        if any(value < 1 for value in values):
            raise ValueError(
                "elevenlabs_chunk_length_schedule values must be positive."
            )

        if len(values) > 16:
            raise ValueError(
                "elevenlabs_chunk_length_schedule cannot exceed 16 values."
            )

        return values


@lru_cache
def get_tts_provider_settings() -> TTSProviderSettings:
    """
    Return cached concrete realtime TTS provider settings.
    """
    return TTSProviderSettings()


class DatabaseSettings(BaseSettings):
    """
    Database connection reliability configuration.

    The PostgreSQL connection timeout is intentionally bounded so
    readiness checks and application database operations fail fast
    instead of waiting indefinitely on unreachable infrastructure.
    """

    db_connect_timeout_seconds: int = Field(
        default=5,
        gt=0,
        le=60,
    )

    model_config = SettingsConfigDict(
        case_sensitive=False,
    )


@lru_cache
def get_database_settings() -> DatabaseSettings:
    """
    Return cached database reliability settings.
    """
    return DatabaseSettings()


class LLMSettings(BaseSettings):
    """
    External LLM provider reliability configuration.

    Timeout and retry bounds are explicit so provider calls cannot
    inherit an unexpectedly long SDK default in production.
    """

    llm_request_timeout_seconds: float = Field(
        default=20.0,
        gt=0,
        le=120,
    )

    llm_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
    )

    model_config = SettingsConfigDict(
        case_sensitive=False,
    )


@lru_cache
def get_llm_settings() -> LLMSettings:
    """
    Return cached LLM provider reliability settings.
    """
    return LLMSettings()


class ObservabilitySettings(BaseSettings):
    """
    API observability and logging configuration.

    Structured JSON is the production default. Text logging remains
    available for local development and troubleshooting.
    """

    api_log_level: Literal[
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ] = "INFO"

    api_log_format: Literal[
        "json",
        "text",
    ] = "json"

    model_config = SettingsConfigDict(
        case_sensitive=False,
    )


@lru_cache
def get_observability_settings() -> ObservabilitySettings:
    """
    Return cached API observability settings.
    """
    return ObservabilitySettings()


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