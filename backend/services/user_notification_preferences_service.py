from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.connection import engine as default_engine
from models.user_notification_preferences import (
    UserNotificationPreferences,
)


class UserNotificationPreferencesService:
    """
    Manage durable per-user notification preferences.

    The service validates timezone and local delivery-time values
    before persistence so downstream schedulers can rely on them.
    """

    DEFAULT_TIMEZONE = "Asia/Karachi"
    DEFAULT_DELIVERY_HOUR = 21
    DEFAULT_DELIVERY_MINUTE = 0
    DEFAULT_DAILY_ACTIVITY_DIGEST_ENABLED = True

    def __init__(self, engine=None):
        self.engine = engine or default_engine

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

    @staticmethod
    def _validate_timezone(
        timezone_name: str,
    ) -> str:
        normalized = str(
            timezone_name
        ).strip()

        if not normalized:
            raise ValueError(
                "timezone cannot be empty."
            )

        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"Invalid timezone: {normalized}"
            ) from exc

        return normalized

    @staticmethod
    def _validate_hour(
        delivery_hour: int,
    ) -> int:
        if (
            isinstance(
                delivery_hour,
                bool,
            )
            or not isinstance(
                delivery_hour,
                int,
            )
        ):
            raise ValueError(
                "delivery_hour must be an integer."
            )

        if not 0 <= delivery_hour <= 23:
            raise ValueError(
                "delivery_hour must be between 0 and 23."
            )

        return delivery_hour

    @staticmethod
    def _validate_minute(
        delivery_minute: int,
    ) -> int:
        if (
            isinstance(
                delivery_minute,
                bool,
            )
            or not isinstance(
                delivery_minute,
                int,
            )
        ):
            raise ValueError(
                "delivery_minute must be an integer."
            )

        if not 0 <= delivery_minute <= 59:
            raise ValueError(
                "delivery_minute must be between 0 and 59."
            )

        return delivery_minute

    @staticmethod
    def _validate_enabled(
        enabled: bool,
    ) -> bool:
        if not isinstance(
            enabled,
            bool,
        ):
            raise ValueError(
                "daily_activity_digest_enabled must be a boolean."
            )

        return enabled

    def get(
        self,
        *,
        user_id: str,
    ) -> UserNotificationPreferences | None:
        normalized_user_id = self._validate_user_id(
            user_id
        )

        with Session(
            self.engine
        ) as session:
            return session.scalar(
                select(
                    UserNotificationPreferences
                ).where(
                    UserNotificationPreferences.user_id
                    == normalized_user_id
                )
            )

    def get_or_create(
        self,
        *,
        user_id: str,
        timezone_name: str | None = None,
        daily_activity_digest_enabled: bool | None = None,
        delivery_hour: int | None = None,
        delivery_minute: int | None = None,
    ) -> UserNotificationPreferences:
        normalized_user_id = self._validate_user_id(
            user_id
        )

        normalized_timezone = self._validate_timezone(
            timezone_name
            if timezone_name is not None
            else self.DEFAULT_TIMEZONE
        )

        normalized_enabled = self._validate_enabled(
            daily_activity_digest_enabled
            if daily_activity_digest_enabled is not None
            else self.DEFAULT_DAILY_ACTIVITY_DIGEST_ENABLED
        )

        normalized_hour = self._validate_hour(
            delivery_hour
            if delivery_hour is not None
            else self.DEFAULT_DELIVERY_HOUR
        )

        normalized_minute = self._validate_minute(
            delivery_minute
            if delivery_minute is not None
            else self.DEFAULT_DELIVERY_MINUTE
        )

        with Session(
            self.engine
        ) as session:
            existing = session.scalar(
                select(
                    UserNotificationPreferences
                ).where(
                    UserNotificationPreferences.user_id
                    == normalized_user_id
                )
            )

            if existing is not None:
                return existing

            preferences = UserNotificationPreferences(
                user_id=normalized_user_id,
                timezone=normalized_timezone,
                daily_activity_digest_enabled=normalized_enabled,
                delivery_hour=normalized_hour,
                delivery_minute=normalized_minute,
            )

            session.add(
                preferences
            )

            try:
                session.commit()
            except IntegrityError:
                session.rollback()

                existing = session.scalar(
                    select(
                        UserNotificationPreferences
                    ).where(
                        UserNotificationPreferences.user_id
                        == normalized_user_id
                    )
                )

                if existing is None:
                    raise

                return existing

            session.refresh(
                preferences
            )

            return preferences

    def update(
        self,
        *,
        user_id: str,
        timezone_name: str | None = None,
        daily_activity_digest_enabled: bool | None = None,
        delivery_hour: int | None = None,
        delivery_minute: int | None = None,
    ) -> UserNotificationPreferences:
        normalized_user_id = self._validate_user_id(
            user_id
        )

        if timezone_name is not None:
            normalized_timezone = self._validate_timezone(
                timezone_name
            )
        else:
            normalized_timezone = None

        if (
            daily_activity_digest_enabled
            is not None
        ):
            normalized_enabled = self._validate_enabled(
                daily_activity_digest_enabled
            )
        else:
            normalized_enabled = None

        if delivery_hour is not None:
            normalized_hour = self._validate_hour(
                delivery_hour
            )
        else:
            normalized_hour = None

        if delivery_minute is not None:
            normalized_minute = self._validate_minute(
                delivery_minute
            )
        else:
            normalized_minute = None

        with Session(
            self.engine
        ) as session:
            preferences = session.scalar(
                select(
                    UserNotificationPreferences
                ).where(
                    UserNotificationPreferences.user_id
                    == normalized_user_id
                )
            )

            if preferences is None:
                preferences = UserNotificationPreferences(
                    user_id=normalized_user_id,
                    timezone=(
                        normalized_timezone
                        or self.DEFAULT_TIMEZONE
                    ),
                    daily_activity_digest_enabled=(
                        normalized_enabled
                        if normalized_enabled is not None
                        else self.DEFAULT_DAILY_ACTIVITY_DIGEST_ENABLED
                    ),
                    delivery_hour=(
                        normalized_hour
                        if normalized_hour is not None
                        else self.DEFAULT_DELIVERY_HOUR
                    ),
                    delivery_minute=(
                        normalized_minute
                        if normalized_minute is not None
                        else self.DEFAULT_DELIVERY_MINUTE
                    ),
                )

                session.add(
                    preferences
                )
            else:
                if normalized_timezone is not None:
                    preferences.timezone = (
                        normalized_timezone
                    )

                if normalized_enabled is not None:
                    preferences.daily_activity_digest_enabled = (
                        normalized_enabled
                    )

                if normalized_hour is not None:
                    preferences.delivery_hour = (
                        normalized_hour
                    )

                if normalized_minute is not None:
                    preferences.delivery_minute = (
                        normalized_minute
                    )

                preferences.updated_at = (
                    self._utc_now_naive()
                )

            session.commit()
            session.refresh(
                preferences
            )

            return preferences