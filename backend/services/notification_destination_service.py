from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.connection import engine as default_engine
from models.notification_destination import (
    NotificationDestination,
)


class NotificationDestinationService:
    """
    Manage durable user notification destinations.

    Provider credentials are intentionally not stored here.
    This service only stores user-facing destination addresses.

    Current supported destination:
    - email
    """

    SUPPORTED_CHANNELS = {
        "email",
    }

    MAX_DESTINATION_LENGTH = 500
    MAX_LABEL_LENGTH = 100

    _EMAIL_PATTERN = re.compile(
        r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )

    def __init__(
        self,
        engine: Any | None = None,
    ):
        self.engine = (
            engine
            if engine is not None
            else default_engine
        )

    @staticmethod
    def _utc_now_naive() -> datetime:
        return datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    @staticmethod
    def _validate_user_id(
        user_id: str,
    ) -> str:
        normalized = str(
            user_id
        ).strip()

        if not normalized:
            raise ValueError(
                "user_id cannot be empty."
            )

        if len(normalized) > 100:
            raise ValueError(
                "user_id cannot exceed 100 characters."
            )

        return normalized

    @classmethod
    def _validate_channel(
        cls,
        channel: str,
    ) -> str:
        normalized = str(
            channel
        ).strip().lower()

        if not normalized:
            raise ValueError(
                "notification channel cannot be empty."
            )

        if normalized not in cls.SUPPORTED_CHANNELS:
            supported = ", ".join(
                sorted(
                    cls.SUPPORTED_CHANNELS
                )
            )

            raise ValueError(
                f"Unsupported notification destination "
                f"channel '{normalized}'. "
                f"Supported channels: {supported}."
            )

        return normalized

    @classmethod
    def _validate_destination(
        cls,
        *,
        channel: str,
        destination: str,
    ) -> str:
        normalized = str(
            destination
        ).strip()

        if not normalized:
            raise ValueError(
                "notification destination cannot be empty."
            )

        if len(normalized) > cls.MAX_DESTINATION_LENGTH:
            raise ValueError(
                "notification destination cannot exceed "
                f"{cls.MAX_DESTINATION_LENGTH} characters."
            )

        if channel == "email":
            if not cls._EMAIL_PATTERN.fullmatch(
                normalized
            ):
                raise ValueError(
                    "Invalid email notification destination."
                )

        return normalized

    @classmethod
    def _validate_label(
        cls,
        label: str | None,
    ) -> str | None:
        if label is None:
            return None

        normalized = str(
            label
        ).strip()

        if not normalized:
            return None

        if len(normalized) > cls.MAX_LABEL_LENGTH:
            raise ValueError(
                "notification destination label cannot exceed "
                f"{cls.MAX_LABEL_LENGTH} characters."
            )

        return normalized

    def create_destination(
        self,
        *,
        user_id: str,
        channel: str,
        destination: str,
        label: str | None = None,
        is_default: bool = False,
    ) -> dict[str, Any]:
        normalized_user_id = (
            self._validate_user_id(
                user_id
            )
        )

        normalized_channel = (
            self._validate_channel(
                channel
            )
        )

        normalized_destination = (
            self._validate_destination(
                channel=normalized_channel,
                destination=destination,
            )
        )

        normalized_label = (
            self._validate_label(
                label
            )
        )

        if not isinstance(
            is_default,
            bool,
        ):
            raise ValueError(
                "is_default must be a boolean."
            )

        now = self._utc_now_naive()

        with Session(
            self.engine
        ) as session:
            existing_enabled = session.scalar(
                select(
                    NotificationDestination
                )
                .where(
                    NotificationDestination.user_id
                    == normalized_user_id,
                    NotificationDestination.channel
                    == normalized_channel,
                    NotificationDestination.is_enabled
                    == True,
                )
                .order_by(
                    NotificationDestination.id.asc()
                )
            )

            effective_default = (
                is_default
                or existing_enabled is None
            )

            if effective_default:
                session.execute(
                    update(
                        NotificationDestination
                    )
                    .where(
                        NotificationDestination.user_id
                        == normalized_user_id,
                        NotificationDestination.channel
                        == normalized_channel,
                        NotificationDestination.is_default
                        == True,
                    )
                    .values(
                        is_default=False,
                        updated_at=now,
                    )
                )

            record = NotificationDestination(
                user_id=normalized_user_id,
                channel=normalized_channel,
                destination=normalized_destination,
                label=normalized_label,
                is_enabled=True,
                is_default=effective_default,
                created_at=now,
                updated_at=now,
            )

            session.add(
                record
            )

            try:
                session.commit()

            except IntegrityError as exc:
                session.rollback()

                raise ValueError(
                    "This notification destination already exists."
                ) from exc

            session.refresh(
                record
            )

            return self._to_dict(
                record
            )

    def list_destinations(
        self,
        *,
        user_id: str,
        channel: str | None = None,
        include_disabled: bool = True,
    ) -> list[dict[str, Any]]:
        normalized_user_id = (
            self._validate_user_id(
                user_id
            )
        )

        normalized_channel = None

        if channel is not None:
            normalized_channel = (
                self._validate_channel(
                    channel
                )
            )

        statement = (
            select(
                NotificationDestination
            )
            .where(
                NotificationDestination.user_id
                == normalized_user_id
            )
        )

        if normalized_channel is not None:
            statement = statement.where(
                NotificationDestination.channel
                == normalized_channel
            )

        if not include_disabled:
            statement = statement.where(
                NotificationDestination.is_enabled
                == True
            )

        statement = (
            statement
            .order_by(
                NotificationDestination.channel.asc(),
                NotificationDestination.is_default.desc(),
                NotificationDestination.id.asc(),
            )
        )

        with Session(
            self.engine
        ) as session:
            records = session.scalars(
                statement
            ).all()

            return [
                self._to_dict(
                    record
                )
                for record in records
            ]

    def get_default_destination(
        self,
        *,
        user_id: str,
        channel: str,
    ) -> dict[str, Any] | None:
        normalized_user_id = (
            self._validate_user_id(
                user_id
            )
        )

        normalized_channel = (
            self._validate_channel(
                channel
            )
        )

        statement = (
            select(
                NotificationDestination
            )
            .where(
                NotificationDestination.user_id
                == normalized_user_id,
                NotificationDestination.channel
                == normalized_channel,
                NotificationDestination.is_enabled
                == True,
            )
            .order_by(
                NotificationDestination.is_default.desc(),
                NotificationDestination.id.asc(),
            )
            .limit(1)
        )

        with Session(
            self.engine
        ) as session:
            record = session.scalar(
                statement
            )

            if record is None:
                return None

            return self._to_dict(
                record
            )

    def set_default_destination(
        self,
        *,
        user_id: str,
        destination_id: int,
    ) -> dict[str, Any] | None:
        normalized_user_id = (
            self._validate_user_id(
                user_id
            )
        )

        now = self._utc_now_naive()

        with Session(
            self.engine
        ) as session:
            record = session.scalar(
                select(
                    NotificationDestination
                ).where(
                    NotificationDestination.id
                    == destination_id,
                    NotificationDestination.user_id
                    == normalized_user_id,
                )
            )

            if record is None:
                return None

            if not record.is_enabled:
                raise ValueError(
                    "A disabled notification destination "
                    "cannot be made default."
                )

            session.execute(
                update(
                    NotificationDestination
                )
                .where(
                    NotificationDestination.user_id
                    == normalized_user_id,
                    NotificationDestination.channel
                    == record.channel,
                )
                .values(
                    is_default=False,
                    updated_at=now,
                )
            )

            record.is_default = True
            record.updated_at = now

            session.commit()
            session.refresh(
                record
            )

            return self._to_dict(
                record
            )

    def delete_destination(
        self,
        *,
        user_id: str,
        destination_id: int,
    ) -> bool:
        normalized_user_id = (
            self._validate_user_id(
                user_id
            )
        )

        now = self._utc_now_naive()

        with Session(
            self.engine
        ) as session:
            record = session.scalar(
                select(
                    NotificationDestination
                ).where(
                    NotificationDestination.id
                    == destination_id,
                    NotificationDestination.user_id
                    == normalized_user_id,
                )
            )

            if record is None:
                return False

            was_default = (
                record.is_default
            )

            channel = (
                record.channel
            )

            session.delete(
                record
            )

            session.flush()

            if was_default:
                replacement = session.scalar(
                    select(
                        NotificationDestination
                    )
                    .where(
                        NotificationDestination.user_id
                        == normalized_user_id,
                        NotificationDestination.channel
                        == channel,
                        NotificationDestination.is_enabled
                        == True,
                    )
                    .order_by(
                        NotificationDestination.id.asc()
                    )
                    .limit(1)
                )

                if replacement is not None:
                    replacement.is_default = True
                    replacement.updated_at = now

            session.commit()

            return True

    @staticmethod
    def _to_dict(
        record: NotificationDestination,
    ) -> dict[str, Any]:
        return {
            "id": record.id,
            "user_id": record.user_id,
            "channel": record.channel,
            "destination": record.destination,
            "label": record.label,
            "is_enabled": record.is_enabled,
            "is_default": record.is_default,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }