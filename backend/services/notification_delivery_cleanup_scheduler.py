from __future__ import annotations

import asyncio
import logging

from services.notification_delivery_service import (
    NotificationDeliveryService,
)


logger = logging.getLogger(__name__)


class NotificationDeliveryCleanupScheduler:
    """
    Low-frequency maintenance scheduler for durable notification
    delivery records.

    Terminal sent/failed records are retained for a bounded period.
    Active processing claims are protected by the delivery service.
    """

    MAX_CYCLE_BACKOFF_SECONDS = 3600

    def __init__(
        self,
        *,
        interval_seconds: int = 300,
        retention_seconds: int = (
            NotificationDeliveryService.DEFAULT_RETENTION_SECONDS
        ),
        batch_size: int = 500,
        delivery_service: NotificationDeliveryService | None = None,
    ):
        if not 10 <= int(interval_seconds) <= self.MAX_CYCLE_BACKOFF_SECONDS:
            raise ValueError(
                "interval_seconds must be between 10 and 3600"
            )

        if int(retention_seconds) < 1:
            raise ValueError(
                "retention_seconds must be at least 1"
            )

        if not 1 <= int(batch_size) <= 5000:
            raise ValueError(
                "batch_size must be between 1 and 5000"
            )

        self.interval_seconds = int(
            interval_seconds
        )
        self.retention_seconds = int(
            retention_seconds
        )
        self.batch_size = int(
            batch_size
        )
        self.delivery_service = (
            delivery_service
            if delivery_service is not None
            else NotificationDeliveryService()
        )
        self._running = False

    def purge_expired_deliveries(self) -> int:
        return self.delivery_service.purge_expired_deliveries(
            retention_seconds=self.retention_seconds,
            limit=self.batch_size,
        )

    async def run(self) -> None:
        if self._running:
            return

        self._running = True

        logger.info(
            "NOVA notification delivery cleanup scheduler started "
            "(interval=%ss, retention=%ss, batch_size=%s)",
            self.interval_seconds,
            self.retention_seconds,
            self.batch_size,
        )

        consecutive_cycle_failures = 0
        cycle_backoff_seconds = self.interval_seconds

        try:
            while self._running:
                try:
                    deleted = self.purge_expired_deliveries()

                    if deleted:
                        logger.info(
                            "Purged %s expired notification delivery records.",
                            deleted,
                        )

                except Exception:
                    consecutive_cycle_failures += 1
                    cycle_backoff_seconds = max(
                        self.interval_seconds,
                        min(
                            self.MAX_CYCLE_BACKOFF_SECONDS,
                            self.interval_seconds
                            * (
                                2
                                ** min(
                                    consecutive_cycle_failures - 1,
                                    10,
                                )
                            ),
                        ),
                    )
                    logger.exception(
                        "Notification delivery cleanup cycle failed "
                        "(consecutive_failures=%s, next_retry_in=%ss).",
                        consecutive_cycle_failures,
                        cycle_backoff_seconds,
                    )

                else:
                    if consecutive_cycle_failures:
                        logger.info(
                            "NOVA notification delivery cleanup scheduler "
                            "recovered after %s consecutive cycle failures.",
                            consecutive_cycle_failures,
                        )

                    consecutive_cycle_failures = 0
                    cycle_backoff_seconds = self.interval_seconds

                if not self._running:
                    break

                await asyncio.sleep(
                    cycle_backoff_seconds
                )

        finally:
            self._running = False

            logger.info(
                "NOVA notification delivery cleanup scheduler stopped."
            )

    def stop(self) -> None:
        self._running = False
