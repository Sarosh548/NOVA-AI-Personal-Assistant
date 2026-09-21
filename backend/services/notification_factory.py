from __future__ import annotations

from config import Settings, get_settings
from services.notification_destination_service import (
    NotificationDestinationService,
)
from services.notification_delivery_service import (
    NotificationDeliveryService,
)
from services.notification_service import (
    ConsoleNotificationChannel,
    EmailNotificationChannel,
    NotificationChannelRegistry,
    NotificationService,
    WebhookNotificationChannel,
)


def build_notification_service(
    settings: Settings | None = None,
    destination_service: (
        NotificationDestinationService | None
    ) = None,
) -> NotificationService:
    """
    Build the application-wide notification service.

    Provider construction is isolated here so application services
    do not need to know about SMTP/webhook environment variables.
    """

    resolved_settings = (
        settings
        if settings is not None
        else get_settings()
    )

    registry = (
        NotificationChannelRegistry()
    )

    registry.register(
        "console",
        ConsoleNotificationChannel(),
    )

    webhook_url = (
        resolved_settings.notification_webhook_url
    )

    if webhook_url is not None:
        normalized_webhook_url = (
            str(webhook_url).strip()
        )

        if normalized_webhook_url:
            registry.register(
                "webhook",
                WebhookNotificationChannel(
                    endpoint_url=(
                        normalized_webhook_url
                    ),
                    secret=(
                        resolved_settings
                        .notification_webhook_secret
                    ),
                    timeout_seconds=(
                        resolved_settings
                        .notification_webhook_timeout_seconds
                    ),
                ),
            )

    smtp_host = (
        resolved_settings.notification_smtp_host
    )

    smtp_from = (
        resolved_settings
        .notification_email_from_address
    )

    smtp_username = (
        resolved_settings
        .notification_smtp_username
    )

    smtp_password = (
        resolved_settings
        .notification_smtp_password
    )

    if smtp_host is not None or smtp_from is not None:
        if not str(
            smtp_host or ""
        ).strip():
            raise ValueError(
                "notification_smtp_host is required "
                "when email notifications are configured."
            )

        if not str(
            smtp_from or ""
        ).strip():
            raise ValueError(
                "notification_email_from_address is required "
                "when email notifications are configured."
            )

        registry.register(
            "email",
            EmailNotificationChannel(
                host=str(
                    smtp_host
                ).strip(),
                port=(
                    resolved_settings
                    .notification_smtp_port
                ),
                from_address=str(
                    smtp_from
                ).strip(),
                username=smtp_username,
                password=smtp_password,
                starttls=(
                    resolved_settings
                    .notification_smtp_starttls
                ),
                use_ssl=(
                    resolved_settings
                    .notification_smtp_use_ssl
                ),
                timeout_seconds=(
                    resolved_settings
                    .notification_smtp_timeout_seconds
                ),
            ),
        )

    default_channel = (
        str(
            resolved_settings
            .notification_default_channel
        )
        .strip()
        .lower()
    )

    if not default_channel:
        raise ValueError(
            "notification_default_channel cannot be empty."
        )

    if not registry.has(
        default_channel
    ):
        if default_channel == "webhook":
            raise ValueError(
                "notification_default_channel is 'webhook' "
                "but notification_webhook_url is not configured."
            )

        if default_channel == "email":
            raise ValueError(
                "notification_default_channel is 'email' "
                "but SMTP email configuration is not complete."
            )

        raise ValueError(
            "Configured notification channel "
            f"'{default_channel}' is not available."
        )

    return NotificationService(
        channel_registry=registry,
        default_channel=default_channel,
        destination_service=(
            destination_service
            if destination_service is not None
            else NotificationDestinationService()
        ),
        delivery_service=NotificationDeliveryService(),
    )
