from __future__ import annotations

import pytest

from config import Settings
from services.notification_factory import (
    build_notification_service,
)
from services.notification_service import (
    ConsoleNotificationChannel,
    EmailNotificationChannel,
    WebhookNotificationChannel,
)


def build_settings(
    **overrides,
):
    values = {
        "auth_jwt_secret_key": (
            "a" * 32
        ),
    }

    values.update(
        overrides
    )

    return Settings(
        **values
    )


def test_factory_defaults_to_console_channel():
    settings = build_settings()

    service = build_notification_service(
        settings=settings
    )

    assert service.default_channel == (
        "console"
    )

    assert service.channel_registry.has(
        "console"
    )

    channel = (
        service.channel_registry.get(
            "console"
        )
    )

    assert isinstance(
        channel,
        ConsoleNotificationChannel,
    )


def test_factory_registers_webhook_when_configured():
    settings = build_settings(
        notification_webhook_url=(
            "https://example.com/notify"
        ),
        notification_webhook_secret=(
            "test-secret"
        ),
        notification_webhook_timeout_seconds=15,
    )

    service = build_notification_service(
        settings=settings
    )

    assert service.default_channel == (
        "console"
    )

    assert service.channel_registry.has(
        "webhook"
    )

    channel = (
        service.channel_registry.get(
            "webhook"
        )
    )

    assert isinstance(
        channel,
        WebhookNotificationChannel,
    )


def test_factory_registers_email_when_smtp_is_configured():
    settings = build_settings(
        notification_smtp_host=(
            "smtp.example.com"
        ),
        notification_smtp_port=587,
        notification_email_from_address=(
            "nova@example.com"
        ),
        notification_smtp_username=(
            "smtp-user"
        ),
        notification_smtp_password=(
            "smtp-password"
        ),
    )

    service = build_notification_service(
        settings=settings
    )

    assert service.channel_registry.has(
        "email"
    )

    channel = (
        service.channel_registry.get(
            "email"
        )
    )

    assert isinstance(
        channel,
        EmailNotificationChannel,
    )

    assert channel.host == (
        "smtp.example.com"
    )

    assert channel.port == 587


def test_factory_can_select_email_as_default():
    settings = build_settings(
        notification_default_channel=(
            "email"
        ),
        notification_smtp_host=(
            "smtp.example.com"
        ),
        notification_email_from_address=(
            "nova@example.com"
        ),
    )

    service = build_notification_service(
        settings=settings
    )

    assert service.default_channel == (
        "email"
    )


def test_factory_rejects_email_default_without_smtp():
    settings = build_settings(
        notification_default_channel=(
            "email"
        ),
    )

    with pytest.raises(
        ValueError,
        match=(
            "notification_default_channel is 'email'"
        ),
    ):
        build_notification_service(
            settings=settings
        )


def test_factory_rejects_partial_smtp_configuration():
    settings = build_settings(
        notification_smtp_host=(
            "smtp.example.com"
        ),
    )

    with pytest.raises(
        ValueError,
        match=(
            "notification_email_from_address is required"
        ),
    ):
        build_notification_service(
            settings=settings
        )


def test_factory_rejects_webhook_default_without_url():
    settings = build_settings(
        notification_default_channel=(
            "webhook"
        ),
    )

    with pytest.raises(
        ValueError,
        match=(
            "notification_default_channel is 'webhook'"
        ),
    ):
        build_notification_service(
            settings=settings
        )


def test_factory_rejects_unknown_default_channel():
    settings = build_settings(
        notification_default_channel=(
            "telegram"
        ),
    )

    with pytest.raises(
        ValueError,
        match=(
            "Configured notification channel "
            "'telegram' is not available"
        ),
    ):
        build_notification_service(
            settings=settings
        )


def test_factory_normalizes_default_channel():
    settings = build_settings(
        notification_default_channel=(
            "  CONSOLE  "
        ),
    )

    service = build_notification_service(
        settings=settings
    )

    assert service.default_channel == (
        "console"
    )