from __future__ import annotations

import json
import logging
import smtplib
from dataclasses import dataclass, field
from hashlib import sha256
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Notification:
    """
    Domain-level notification payload.

    The notification describes WHAT NOVA wants to deliver.
    Delivery channels decide HOW and WHERE it is delivered.

    destination is optional because:
    - console uses no external destination
    - webhook uses its configured server-side endpoint
    - email can resolve a durable per-user destination
    """

    user_id: str
    notification_type: str
    title: str
    body: str
    metadata: dict[str, Any] = field(
        default_factory=dict
    )
    destination: str | None = None
    idempotency_key: str | None = None


class NotificationChannel(Protocol):
    """
    Delivery interface for notification providers.
    """

    def send(
        self,
        notification: Notification,
    ) -> bool:
        ...


class NotificationDestinationResolver(Protocol):
    """
    Optional destination lookup interface used by
    NotificationService for provider-backed user destinations.
    """

    def get_default_destination(
        self,
        *,
        user_id: str,
        channel: str,
    ) -> dict[str, Any] | None:
        ...


class EmailDeliveryPort(Protocol):
    """
    Provider-backed email delivery contract.

    Agent tools can depend on this capability without depending
    on a concrete SMTP implementation.
    """

    def send_email(
        self,
        *,
        user_id: str,
        to: str | list[str] | tuple[str, ...],
        subject: str,
        body: str,
        cc: str | list[str] | tuple[str, ...] | None = None,
        bcc: str | list[str] | tuple[str, ...] | None = None,
        message_id: str | None = None,
    ) -> bool:
        ...


class NotificationChannelRegistry:
    """
    Registry for named notification delivery channels.

    Provider selection stays separate from domain-level
    notification creation.
    """

    def __init__(
        self,
    ):
        self._channels: dict[
            str,
            NotificationChannel,
        ] = {}

    @staticmethod
    def _normalize_name(
        name: str,
    ) -> str:
        normalized = str(
            name
        ).strip().lower()

        if not normalized:
            raise ValueError(
                "Notification channel name cannot be empty."
            )

        return normalized

    def register(
        self,
        name: str,
        channel: NotificationChannel,
    ) -> None:
        normalized_name = (
            self._normalize_name(
                name
            )
        )

        if channel is None:
            raise ValueError(
                "Notification channel cannot be None."
            )

        if normalized_name in self._channels:
            raise ValueError(
                f"Notification channel "
                f"'{normalized_name}' is already registered."
            )

        self._channels[
            normalized_name
        ] = channel

    def unregister(
        self,
        name: str,
    ) -> bool:
        normalized_name = (
            self._normalize_name(
                name
            )
        )

        return (
            self._channels.pop(
                normalized_name,
                None,
            )
            is not None
        )

    def get(
        self,
        name: str,
    ) -> NotificationChannel | None:
        normalized_name = (
            self._normalize_name(
                name
            )
        )

        return self._channels.get(
            normalized_name
        )

    def has(
        self,
        name: str,
    ) -> bool:
        normalized_name = (
            self._normalize_name(
                name
            )
        )

        return (
            normalized_name
            in self._channels
        )

    def list_channels(
        self,
    ) -> list[str]:
        return sorted(
            self._channels.keys()
        )


class ConsoleNotificationChannel:
    """
    Development notification adapter.

    This remains the default fallback when no external provider
    has been configured.
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


class EmailNotificationChannel:
    """
    SMTP email notification adapter.

    Credentials are supplied by application configuration and are
    never persisted in NotificationDestination.

    User-specific recipient addresses come from Notification.destination.
    """

    DEFAULT_TIMEOUT_SECONDS = 10

    @staticmethod
    def _build_idempotent_message_id(
        idempotency_key: str | None,
    ) -> str | None:
        if not idempotency_key:
            return None

        digest = sha256(
            idempotency_key.encode("utf-8")
        ).hexdigest()[:32]

        return f"<nova-{digest}@nova.local>"

    @staticmethod
    def _validate_email(
        value: str,
        field_name: str,
    ) -> str:
        normalized = str(
            value
        ).strip()

        if not normalized:
            raise ValueError(
                f"{field_name} cannot be empty."
            )

        _, parsed_address = parseaddr(
            normalized
        )

        if (
            parsed_address != normalized
            or "@"
            not in normalized
            or normalized.startswith("@")
            or normalized.endswith("@")
        ):
            raise ValueError(
                f"{field_name} must be a valid email address."
            )

        local_part, _, domain = (
            normalized.rpartition("@")
        )

        if (
            not local_part
            or not domain
            or "." not in domain
        ):
            raise ValueError(
                f"{field_name} must be a valid email address."
            )

        return normalized

    def __init__(
        self,
        *,
        host: str,
        port: int,
        from_address: str,
        username: str | None = None,
        password: str | None = None,
        starttls: bool = True,
        use_ssl: bool = False,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        normalized_host = str(
            host
        ).strip()

        if not normalized_host:
            raise ValueError(
                "SMTP host cannot be empty."
            )

        if (
            isinstance(
                port,
                bool,
            )
            or not isinstance(
                port,
                int,
            )
            or not 1 <= port <= 65535
        ):
            raise ValueError(
                "SMTP port must be an integer between 1 and 65535."
            )

        if (
            isinstance(
                timeout_seconds,
                bool,
            )
            or not isinstance(
                timeout_seconds,
                int,
            )
            or timeout_seconds < 1
        ):
            raise ValueError(
                "timeout_seconds must be an integer greater than zero."
            )

        if (
            starttls
            and use_ssl
        ):
            raise ValueError(
                "SMTP starttls and SSL cannot both be enabled."
            )

        normalized_from = (
            self._validate_email(
                from_address,
                "SMTP from_address",
            )
        )

        normalized_username = (
            None
            if username is None
            else str(username).strip()
        )

        normalized_password = (
            None
            if password is None
            else str(password)
        )

        if normalized_username and normalized_password is None:
            raise ValueError(
                "SMTP password is required when SMTP username is configured."
            )

        if normalized_password is not None and not normalized_username:
            raise ValueError(
                "SMTP username is required when SMTP password is configured."
            )

        self.host = (
            normalized_host
        )
        self.port = port
        self.from_address = (
            normalized_from
        )
        self.username = (
            normalized_username
        )
        self.password = (
            normalized_password
        )
        self.starttls = bool(
            starttls
        )
        self.use_ssl = bool(
            use_ssl
        )
        self.timeout_seconds = (
            timeout_seconds
        )

    @classmethod
    def _normalize_recipients(
        cls,
        value: str | list[str] | tuple[str, ...] | None,
        field_name: str,
    ) -> list[str]:
        if value is None:
            return []

        if isinstance(value, str):
            raw_values = value.split(",")
        elif isinstance(value, (list, tuple)):
            raw_values = list(value)
        else:
            raise ValueError(
                f"{field_name} must be a string or list of strings."
            )

        normalized: list[str] = []
        seen: set[str] = set()

        for item in raw_values:
            address = cls._validate_email(
                str(item),
                field_name,
            )

            key = address.casefold()

            if key in seen:
                continue

            seen.add(key)
            normalized.append(address)

        return normalized

    def send_email(
        self,
        *,
        user_id: str,
        to: str | list[str] | tuple[str, ...],
        subject: str,
        body: str,
        cc: str | list[str] | tuple[str, ...] | None = None,
        bcc: str | list[str] | tuple[str, ...] | None = None,
        message_id: str | None = None,
    ) -> bool:
        normalized_subject = str(
            subject
        ).strip()

        normalized_body = str(
            body
        ).strip()

        if not normalized_subject:
            raise ValueError(
                "Email subject cannot be empty."
            )

        if not normalized_body:
            raise ValueError(
                "Email body cannot be empty."
            )

        try:
            normalized_to = self._normalize_recipients(
                to,
                "Email recipient",
            )

            normalized_cc = self._normalize_recipients(
                cc,
                "Email CC recipient",
            )

            normalized_bcc = self._normalize_recipients(
                bcc,
                "Email BCC recipient",
            )

            all_recipients = {
                address.casefold()
                for address in (
                    normalized_to
                    + normalized_cc
                    + normalized_bcc
                )
            }

            if not all_recipients:
                raise ValueError(
                    "At least one email recipient is required."
                )

            message = EmailMessage()

            message["From"] = (
                self.from_address
            )

            if normalized_to:
                message["To"] = ", ".join(
                    normalized_to
                )

            if normalized_cc:
                message["Cc"] = ", ".join(
                    normalized_cc
                )

            if normalized_bcc:
                message["Bcc"] = ", ".join(
                    normalized_bcc
                )

            message["Subject"] = (
                normalized_subject[:200]
            )

            if message_id:
                message["Message-ID"] = message_id

            message.set_content(
                normalized_body[:10000]
            )

            smtp_class = (
                smtplib.SMTP_SSL
                if self.use_ssl
                else smtplib.SMTP
            )

            with smtp_class(
                self.host,
                self.port,
                timeout=self.timeout_seconds,
            ) as smtp:
                if self.starttls:
                    smtp.starttls()

                if self.username:
                    smtp.login(
                        self.username,
                        self.password,
                    )

                smtp.send_message(
                    message
                )

            return True

        except (
            ValueError,
            smtplib.SMTPException,
            OSError,
        ):
            logger.warning(
                "Email delivery failed "
                "for user=%s.",
                user_id,
            )

            return False

        except Exception:
            logger.exception(
                "Unexpected email delivery failure "
                "for user=%s.",
                user_id,
            )

            return False

    def send(
        self,
        notification: Notification,
    ) -> bool:
        recipient = (
            notification.destination
        )

        if not recipient:
            logger.warning(
                "No email destination is configured "
                "for user=%s.",
                notification.user_id,
            )

            return False

        message_id = (
            self._build_idempotent_message_id(
                notification.idempotency_key
            )
        )

        return self.send_email(
            user_id=notification.user_id,
            to=recipient,
            subject=notification.title,
            body=notification.body,
            message_id=message_id,
        )


class WebhookNotificationChannel:
    """
    HTTP webhook notification adapter.

    The endpoint is server-side configuration. User destinations
    are deliberately NOT used here to avoid turning arbitrary
    user-controlled URLs into a server-side request/SSRF surface.
    """

    DEFAULT_TIMEOUT_SECONDS = 10

    def __init__(
        self,
        *,
        endpoint_url: str,
        secret: str | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        normalized_url = str(
            endpoint_url
        ).strip()

        if not normalized_url:
            raise ValueError(
                "endpoint_url cannot be empty."
            )

        parsed = urlparse(
            normalized_url
        )

        if parsed.scheme not in {
            "http",
            "https",
        }:
            raise ValueError(
                "endpoint_url must use http or https."
            )

        if not parsed.netloc:
            raise ValueError(
                "endpoint_url must contain a valid host."
            )

        if (
            isinstance(
                timeout_seconds,
                bool,
            )
            or not isinstance(
                timeout_seconds,
                int,
            )
            or timeout_seconds < 1
        ):
            raise ValueError(
                "timeout_seconds must be an integer "
                "greater than zero."
            )

        normalized_secret = (
            None
            if secret is None
            else str(secret)
        )

        self.endpoint_url = (
            normalized_url
        )

        self.secret = (
            normalized_secret
            if normalized_secret
            else None
        )

        self.timeout_seconds = (
            timeout_seconds
        )

    @staticmethod
    def _build_payload(
        notification: Notification,
    ) -> dict[str, Any]:
        return {
            "user_id": notification.user_id,
            "notification_type": (
                notification.notification_type
            ),
            "title": notification.title,
            "body": notification.body,
            "metadata": dict(
                notification.metadata
            ),
        }

    def send(
        self,
        notification: Notification,
    ) -> bool:
        payload = self._build_payload(
            notification
        )

        try:
            encoded_payload = json.dumps(
                payload,
                default=self._json_default,
            ).encode(
                "utf-8"
            )

        except (TypeError, ValueError):
            logger.exception(
                "Could not serialize webhook notification "
                "for user=%s.",
                notification.user_id,
            )

            return False

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "NOVA-NotificationClient/1.0",
        }

        if self.secret:
            headers[
                "X-NOVA-Notification-Secret"
            ] = self.secret

        if notification.idempotency_key:
            headers[
                "Idempotency-Key"
            ] = notification.idempotency_key

        request = Request(
            self.endpoint_url,
            data=encoded_payload,
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                status_code = int(
                    response.status
                )

                return (
                    200
                    <= status_code
                    < 300
                )

        except HTTPError as exc:
            logger.warning(
                "Webhook notification provider returned "
                "HTTP %s for user=%s.",
                exc.code,
                notification.user_id,
            )

            return False

        except (
            URLError,
            TimeoutError,
            OSError,
        ):
            logger.warning(
                "Webhook notification delivery failed "
                "for user=%s.",
                notification.user_id,
            )

            return False

        except Exception:
            logger.exception(
                "Unexpected webhook notification failure "
                "for user=%s.",
                notification.user_id,
            )

            return False

    @staticmethod
    def _json_default(
        value: Any,
    ) -> str:
        return str(value)


class NotificationService:
    """
    Domain-level notification service.

    The service decides WHAT notification is being sent.
    Channels decide HOW it is delivered.

    User-specific destination resolution is delegated to the
    notification destination service and currently applies to
    the email channel only.
    """

    DEFAULT_CHANNEL = "console"

    def __init__(
        self,
        channel: NotificationChannel | None = None,
        *,
        channel_registry: (
            NotificationChannelRegistry | None
        ) = None,
        default_channel: str = DEFAULT_CHANNEL,
        destination_service: (
            NotificationDestinationResolver | None
        ) = None,
    ):
        self.channel_registry = (
            channel_registry
            if channel_registry is not None
            else NotificationChannelRegistry()
        )

        normalized_default = (
            NotificationChannelRegistry
            ._normalize_name(
                default_channel
            )
        )

        if channel is not None:
            if self.channel_registry.has(
                normalized_default
            ):
                raise ValueError(
                    f"Notification channel "
                    f"'{normalized_default}' is already registered."
                )

            self.channel_registry.register(
                normalized_default,
                channel,
            )

        elif not self.channel_registry.has(
            normalized_default
        ):
            self.channel_registry.register(
                normalized_default,
                ConsoleNotificationChannel(),
            )

        self.default_channel = (
            normalized_default
        )

        self.destination_service = (
            destination_service
        )

    def send_email(
        self,
        *,
        user_id: str,
        to: str | list[str] | tuple[str, ...] | None = None,
        subject: str,
        body: str,
        cc: str | list[str] | tuple[str, ...] | None = None,
        bcc: str | list[str] | tuple[str, ...] | None = None,
    ) -> bool:
        """Send an outbound email through the registered email channel."""
        resolved_to = to

        if resolved_to is None and self.destination_service is not None:
            destination_record = self.destination_service.get_default_destination(
                user_id=user_id,
                channel="email",
            )

            if destination_record is not None:
                resolved_to = destination_record.get("destination")

        if resolved_to is None:
            logger.warning(
                "No email destination is configured for user=%s.",
                user_id,
            )
            return False

        delivery_channel = self.channel_registry.get("email")

        if delivery_channel is None:
            logger.warning("Email notification channel is not configured.")
            return False

        sender = getattr(delivery_channel, "send_email", None)

        if not callable(sender):
            logger.error(
                "Registered email channel does not support direct email delivery."
            )
            return False

        return bool(sender(
            user_id=user_id,
            to=resolved_to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
        ))

    def notify(
        self,
        *,
        user_id: str,
        title: str,
        body: str,
        notification_type: str = "general",
        metadata: dict[str, Any] | None = None,
        channel: str | None = None,
        destination: str | None = None,
        idempotency_key: str | None = None,
    ) -> bool:
        cleaned_user_id = (
            user_id.strip()
        )

        cleaned_title = (
            title.strip()
        )

        cleaned_body = (
            body.strip()
        )

        cleaned_type = (
            notification_type.strip()
        )

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

        selected_channel = (
            self.default_channel
            if channel is None
            else NotificationChannelRegistry
            ._normalize_name(
                channel
            )
        )

        delivery_channel = (
            self.channel_registry.get(
                selected_channel
            )
        )

        if delivery_channel is None:
            logger.warning(
                "Notification channel '%s' is not registered.",
                selected_channel,
            )

            return False

        resolved_destination = (
            destination
        )

        if (
            resolved_destination is None
            and selected_channel == "email"
            and self.destination_service is not None
        ):
            try:
                destination_record = (
                    self.destination_service
                    .get_default_destination(
                        user_id=cleaned_user_id,
                        channel="email",
                    )
                )

                if destination_record is not None:
                    resolved_destination = (
                        destination_record.get(
                            "destination"
                        )
                    )

            except Exception:
                logger.exception(
                    "Could not resolve default notification "
                    "destination for user=%s.",
                    cleaned_user_id,
                )

                return False

        normalized_idempotency_key = (
            None
            if idempotency_key is None
            else str(idempotency_key).strip()
        )

        if (
            normalized_idempotency_key is not None
            and not normalized_idempotency_key
        ):
            raise ValueError(
                "Notification idempotency_key cannot be empty."
            )

        if (
            normalized_idempotency_key is not None
            and len(normalized_idempotency_key) > 255
        ):
            raise ValueError(
                "Notification idempotency_key cannot exceed 255 characters."
            )

        notification = Notification(
            user_id=cleaned_user_id,
            notification_type=cleaned_type,
            title=cleaned_title[:200],
            body=cleaned_body[:2000],
            metadata=dict(
                metadata or {}
            ),
            destination=(
                resolved_destination
            ),
            idempotency_key=(
                normalized_idempotency_key
            ),
        )

        try:
            return bool(
                delivery_channel.send(
                    notification
                )
            )

        except Exception:
            logger.exception(
                "Notification delivery failed "
                "for user=%s through channel=%s.",
                cleaned_user_id,
                selected_channel,
            )

            return False