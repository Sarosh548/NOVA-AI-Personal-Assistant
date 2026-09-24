from __future__ import annotations

import asyncio
import logging

from services.idempotency_service import (
    IdempotencyService,
)


logger = logging.getLogger(__name__)


class IdempotencyCleanupScheduler:
    """
    Low-frequency maintenance scheduler for durable idempotency records.

    Only expired completed/failed records are removed. Active
    processing claims are left untouched.
    """

    MAX_CYCLE_BACKOFF_SECONDS = 3600

    def __init__(
        self,
        *,
        interval_seconds: int = 300,
        idempotency_service: IdempotencyService | None = None,
        batch_size: int = 500,
    ):
        if interval_seconds < 10:
            raise ValueError(
                "interval_seconds must be at least 10"
            )

        if (
            interval_seconds
            > self.MAX_CYCLE_BACKOFF_SECONDS
        ):
            raise ValueError(
                "interval_seconds must not exceed "
                "MAX_CYCLE_BACKOFF_SECONDS"
            )

        if not isinstance(
            batch_size,
            int,
        ) or isinstance(
            batch_size,
            bool,
        ):
            raise ValueError(
                "batch_size must be an integer."
            )

        if not 1 <= batch_size <= 5000:
            raise ValueError(
                "batch_size must be between 1 and 5000."
            )

        self.interval_seconds = interval_seconds
        self.idempotency_service = (
            idempotency_service
            if idempotency_service is not None
            else IdempotencyService()
        )
        self.batch_size = batch_size
        self._running = False

    def _process_expired_records_sync(self) -> int:
        """
        Purge one bounded batch of expired terminal records.
        """
        return self.idempotency_service.purge_expired_records(
            limit=self.batch_size
        )

    async def process_expired_records(self) -> int:
        """
        Run the blocking cleanup cycle outside the asyncio event loop.
        """
        return await asyncio.to_thread(
            self._process_expired_records_sync
        )

    async def run(self) -> None:
        """
        Run the cleanup loop until stopped.
        """
        if self._running:
            return

        self._running = True

        logger.info(
            "NOVA idempotency cleanup scheduler started "
            "(interval=%ss, batch_size=%s)",
            self.interval_seconds,
            self.batch_size,
        )

        consecutive_cycle_failures = 0
        cycle_backoff_seconds = self.interval_seconds

        try:
            while self._running:
                try:
                    await self.process_expired_records()

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
                        "Unexpected idempotency cleanup cycle failure "
                        "(consecutive_failures=%s, "
                        "next_retry_in=%ss).",
                        consecutive_cycle_failures,
                        cycle_backoff_seconds,
                    )

                else:
                    if consecutive_cycle_failures:
                        logger.info(
                            "NOVA idempotency cleanup scheduler recovered "
                            "after %s consecutive cycle failures.",
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
                "NOVA idempotency cleanup scheduler stopped."
            )

    def stop(self) -> None:
        """
        Stop the scheduler loop after the current cycle.
        """
        self._running = False
