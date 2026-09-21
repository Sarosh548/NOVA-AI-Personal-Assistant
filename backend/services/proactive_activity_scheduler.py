from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from services.activity_event_service import (
    ActivityEventService,
)
from services.proactive_activity_notification_service import (
    ProactiveActivityNotificationService,
)
from services.user_notification_preferences_service import (
    UserNotificationPreferencesService,
)


logger = logging.getLogger(__name__)


class ProactiveActivityScheduler:
    """
    Background scheduler for proactive daily activity digests.

    Each user is evaluated using that user's durable notification
    preferences:

    - timezone
    - daily digest enabled/disabled
    - local delivery hour
    - local delivery minute

    The scheduler discovers recent activity broadly enough to cover
    users across global timezones, then checks each user's own local
    calendar day before delegating durable notification delivery.

    This service does NOT:
    - build report contents
    - send notifications directly
    - call the LLM
    - bypass durable delivery protection
    """

    DEFAULT_TIMEZONE = "Asia/Karachi"
    DEFAULT_DELIVERY_HOUR = 21
    DEFAULT_DELIVERY_MINUTE = 0

    ACTIVITY_DISCOVERY_LOOKBACK_HOURS = 36

    def __init__(
        self,
        *,
        interval_seconds: int = 5,
        activity_event_service: (
            ActivityEventService | None
        ) = None,
        notification_service: (
            ProactiveActivityNotificationService | None
        ) = None,
        preferences_service: (
            UserNotificationPreferencesService | None
        ) = None,
    ):
        if interval_seconds < 1:
            raise ValueError(
                "interval_seconds must be at least 1"
            )

        self.interval_seconds = interval_seconds

        self.activity_event_service = (
            activity_event_service
            if activity_event_service is not None
            else ActivityEventService()
        )

        self.notification_service = (
            notification_service
            if notification_service is not None
            else ProactiveActivityNotificationService()
        )

        self.preferences_service = (
            preferences_service
            if preferences_service is not None
            else UserNotificationPreferencesService()
        )

        self._running = False

    @staticmethod
    def _normalize_now(
        now: datetime | None,
    ) -> datetime:
        if now is None:
            return datetime.now(
                timezone.utc
            )

        if now.tzinfo is None:
            return now.replace(
                tzinfo=timezone.utc
            )

        return now.astimezone(
            timezone.utc
        )

    @staticmethod
    def _resolve_timezone(
        timezone_name: str,
    ) -> ZoneInfo:
        try:
            return ZoneInfo(
                str(timezone_name).strip()
            )
        except Exception as exc:
            raise ValueError(
                f"Invalid user timezone '{timezone_name}'."
            ) from exc

    @classmethod
    def _local_day_window(
        cls,
        *,
        timezone_name: str,
        now: datetime,
    ) -> tuple[datetime, datetime]:
        user_timezone = cls._resolve_timezone(
            timezone_name
        )

        local_now = now.astimezone(
            user_timezone
        )

        local_start = datetime.combine(
            local_now.date(),
            time.min,
            tzinfo=user_timezone,
        )

        local_end = local_start + timedelta(
            days=1
        )

        utc_start = local_start.astimezone(
            timezone.utc
        ).replace(
            tzinfo=None
        )

        utc_end = local_end.astimezone(
            timezone.utc
        ).replace(
            tzinfo=None
        )

        return (
            utc_start,
            utc_end,
        )

    @classmethod
    def is_due(
        cls,
        *,
        preferences: Any,
        now: datetime | None = None,
    ) -> bool:
        """
        Return whether the user's local delivery time has arrived.
        """

        reference_now = cls._normalize_now(
            now
        )

        user_timezone = cls._resolve_timezone(
            preferences.timezone
        )

        local_now = reference_now.astimezone(
            user_timezone
        )

        delivery_time = time(
            int(
                preferences.delivery_hour
            ),
            int(
                preferences.delivery_minute
            ),
        )

        return (
            local_now.time()
            >= delivery_time
        )

    def _has_current_local_day_activity(
        self,
        *,
        user_id: str,
        preferences: Any,
        now: datetime,
    ) -> bool:
        utc_start, utc_end = (
            self._local_day_window(
                timezone_name=preferences.timezone,
                now=now,
            )
        )

        events = (
            self.activity_event_service
            .list_events(
                user_id=user_id,
                since=utc_start,
                limit=1,
            )
        )

        return any(
            event["created_at"]
            < utc_end
            for event in events
        )

    async def process_daily_activity_digests(
        self,
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Process due daily activity digests for all users who have
        recent activity.

        Recent activity discovery spans enough UTC time to cover the
        current local day for users across the global timezone range.

        The upper discovery bound includes events created exactly at
        the scheduler reference time.
        """

        reference_now = self._normalize_now(
            now
        )

        discovery_start = (
            reference_now
            - timedelta(
                hours=(
                    self.ACTIVITY_DISCOVERY_LOOKBACK_HOURS
                )
            )
        ).replace(
            tzinfo=None
        )

        discovery_end = (
            reference_now.replace(
                tzinfo=None
            )
            + timedelta(
                microseconds=1
            )
        )

        user_ids = (
            self.activity_event_service
            .list_users_with_activity_since(
                since=discovery_start,
                until=discovery_end,
            )
        )

        results: list[dict[str, Any]] = []

        for user_id in user_ids:
            try:
                preferences = (
                    self.preferences_service
                    .get_or_create(
                        user_id=user_id
                    )
                )

                if (
                    not preferences
                    .daily_activity_digest_enabled
                ):
                    results.append(
                        {
                            "user_id": user_id,
                            "result": {
                                "delivered": False,
                                "skipped": True,
                                "reason": (
                                    "digest_disabled"
                                ),
                            },
                        }
                    )
                    continue

                if not self.is_due(
                    preferences=preferences,
                    now=reference_now,
                ):
                    results.append(
                        {
                            "user_id": user_id,
                            "result": {
                                "delivered": False,
                                "skipped": True,
                                "reason": (
                                    "not_due"
                                ),
                            },
                        }
                    )
                    continue

                if not self._has_current_local_day_activity(
                    user_id=user_id,
                    preferences=preferences,
                    now=reference_now,
                ):
                    results.append(
                        {
                            "user_id": user_id,
                            "result": {
                                "delivered": False,
                                "skipped": True,
                                "reason": (
                                    "no_activity"
                                ),
                            },
                        }
                    )
                    continue

                result = (
                    self.notification_service
                    .deliver_daily_activity_digest(
                        user_id=user_id,
                        now=reference_now,
                    )
                )

                results.append(
                    {
                        "user_id": user_id,
                        "result": result,
                    }
                )

            except Exception:
                logger.exception(
                    "Proactive activity digest processing "
                    "failed for user=%s.",
                    user_id,
                )

                results.append(
                    {
                        "user_id": user_id,
                        "result": {
                            "delivered": False,
                            "skipped": False,
                            "reason": (
                                "scheduler_exception"
                            ),
                        },
                    }
                )

        return results

    async def run(self) -> None:
        if self._running:
            return

        self._running = True

        logger.info(
            "NOVA proactive activity scheduler started "
            "(interval=%ss, discovery_lookback=%sh)",
            self.interval_seconds,
            self.ACTIVITY_DISCOVERY_LOOKBACK_HOURS,
        )

        try:
            while self._running:
                try:
                    await self.process_daily_activity_digests()

                except Exception:
                    logger.exception(
                        "Unexpected proactive activity scheduler cycle failure."
                    )

                if not self._running:
                    break

                await asyncio.sleep(
                    self.interval_seconds
                )

        finally:
            self._running = False

            logger.info(
                "NOVA proactive activity scheduler stopped."
            )

    def stop(self) -> None:
        self._running = False