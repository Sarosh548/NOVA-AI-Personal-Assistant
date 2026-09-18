from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from services.activity_event_service import (
    ActivityEventService,
)
from services.proactive_activity_notification_service import (
    ProactiveActivityNotificationService,
)


logger = logging.getLogger(__name__)


class ProactiveActivityScheduler:
    """
    Background scheduler for proactive daily activity digests.

    Responsibilities:
    - poll on a lightweight interval
    - detect when the configured local delivery time has arrived
    - discover users with activity during the current local day
    - delegate durable notification delivery
    - allow failed deliveries to retry on later polling cycles

    Does not:
    - build report contents itself
    - send notifications directly
    - call the LLM
    - bypass durable delivery protection
    """

    DEFAULT_TIMEZONE = "Asia/Karachi"

    def __init__(
        self,
        *,
        interval_seconds: int = 5,
        delivery_hour: int = 21,
        delivery_minute: int = 0,
        timezone_name: str = DEFAULT_TIMEZONE,
        activity_event_service: (
            ActivityEventService | None
        ) = None,
        notification_service: (
            ProactiveActivityNotificationService | None
        ) = None,
    ):
        if interval_seconds < 1:
            raise ValueError(
                "interval_seconds must be at least 1"
            )

        if not 0 <= delivery_hour <= 23:
            raise ValueError(
                "delivery_hour must be between 0 and 23"
            )

        if not 0 <= delivery_minute <= 59:
            raise ValueError(
                "delivery_minute must be between 0 and 59"
            )

        try:
            self.timezone = ZoneInfo(
                timezone_name
            )
        except Exception as exc:
            raise ValueError(
                f"Invalid scheduler timezone '{timezone_name}'."
            ) from exc

        self.interval_seconds = interval_seconds
        self.delivery_time = time(
            delivery_hour,
            delivery_minute,
        )

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

        self._running = False

    def is_due(
        self,
        *,
        now: datetime | None = None,
    ) -> bool:
        """
        Return whether today's local digest delivery time has arrived.
        """

        if now is None:
            now = datetime.now(
                timezone.utc
            )

        if now.tzinfo is None:
            now = now.replace(
                tzinfo=timezone.utc
            )

        local_now = now.astimezone(
            self.timezone
        )

        return (
            local_now.time()
            >= self.delivery_time
        )

    def get_current_local_day_window(
        self,
        *,
        now: datetime | None = None,
    ) -> tuple[datetime, datetime]:
        """
        Return today's local calendar day as naive UTC datetimes.
        """

        if now is None:
            now = datetime.now(
                timezone.utc
            )

        if now.tzinfo is None:
            now = now.replace(
                tzinfo=timezone.utc
            )

        local_now = now.astimezone(
            self.timezone
        )

        local_start = datetime.combine(
            local_now.date(),
            time.min,
            tzinfo=self.timezone,
        )

        local_end = datetime.combine(
            local_now.date(),
            time.max,
            tzinfo=self.timezone,
        )

        utc_start = local_start.astimezone(
            timezone.utc
        ).replace(
            tzinfo=None
        )

        utc_end = (
            local_end.astimezone(
                timezone.utc
            ).replace(
                tzinfo=None
            )
        )

        return (
            utc_start,
            utc_end,
        )

    async def process_daily_activity_digests(
        self,
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Process today's proactive activity digests.

        Users are discovered from today's activity events.
        Durable delivery state decides whether a user should
        actually receive a notification.
        """

        reference_now = (
            self._normalize_now(
                now
            )
        )

        if not self.is_due(
            now=reference_now
        ):
            return []

        utc_start, utc_end = (
            self.get_current_local_day_window(
                now=reference_now
            )
        )

        user_ids = (
            self.activity_event_service
            .list_users_with_activity_since(
                since=utc_start,
                until=utc_end,
            )
        )

        results = []

        for user_id in user_ids:
            try:
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

    async def run(self) -> None:
        if self._running:
            return

        self._running = True

        logger.info(
            "NOVA proactive activity scheduler started "
            "(interval=%ss, delivery=%s, timezone=%s)",
            self.interval_seconds,
            self.delivery_time.strftime(
                "%H:%M"
            ),
            self.timezone.key,
        )

        try:
            while self._running:
                await self.process_daily_activity_digests()

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