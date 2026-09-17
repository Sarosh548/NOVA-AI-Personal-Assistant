from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Notification:
    user_id: str
    notification_type: str
    title: str
    body: str
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


class NotificationChannel(Protocol):
    """
    Delivery interface.

    Future adapters can implement this for:
    WebSocket, push notifications, mobile, voice, etc.
    """

    def send(
        self,
        notification: Notification,
    ) -> bool:
        ...


class ConsoleNotificationChannel:
    """
    Temporary backend notification adapter.

    This keeps the notification domain separate from the
    eventual UI/mobile delivery mechanisms.
    """

    def send(
        self,
        notification: Notification,
    ) -> bool:
        logger.info(
            "NOTIFICATION | user=%s | type=%s | title=%s | body=%s",
            notification.user_id,
            notification.notification_type,
            notification.title,
            notification.body,
        )

        print(
            f"\n[NOVA NOTIFICATION] "
            f"user={notification.user_id} "
            f"type={notification.notification_type} "
            f"title={notification.title} "
            f"body={notification.body}\n"
        )

        return True


class NotificationService:
    """
    Domain-level notification service.

    The service decides what notification is being sent.
    The channel decides how it is delivered.
    """

    def __init__(
        self,
        channel: NotificationChannel | None = None,
    ):
        self.channel = (
            channel
            if channel is not None
            else ConsoleNotificationChannel()
        )

    def notify(
        self,
        *,
        user_id: str,
        title: str,
        body: str,
        notification_type: str = "general",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        cleaned_user_id = user_id.strip()
        cleaned_title = title.strip()
        cleaned_body = body.strip()
        cleaned_type = notification_type.strip()

        if not cleaned_user_id:
            raise ValueError(
                "Notification user_id cannot be empty."
            )

        if not cleaned_title:
            raise ValueError(
                "Notification title cannot be empty."
            )

        if not cleaned_body:
            raise ValueError(
                "Notification body cannot be empty."
            )

        if not cleaned_type:
            raise ValueError(
                "Notification type cannot be empty."
            )

        notification = Notification(
            user_id=cleaned_user_id,
            notification_type=cleaned_type,
            title=cleaned_title[:200],
            body=cleaned_body[:2000],
            metadata=dict(metadata or {}),
        )

        try:
            return bool(
                self.channel.send(
                    notification
                )
            )
        except Exception:
            logger.exception(
                "Notification delivery failed "
                "for user=%s.",
                cleaned_user_id,
            )
            return False