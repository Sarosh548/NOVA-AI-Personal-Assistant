import asyncio
import logging

from services.reminder_service import ReminderService


logger = logging.getLogger(__name__)


class ReminderScheduler:
    """
    Lightweight NOVA reminder scheduler.

    It checks PostgreSQL periodically for due reminders,
    claims them atomically, processes them, and marks them
    completed.
    """

    def __init__(
        self,
        interval_seconds: int = 5,
    ):
        if interval_seconds < 1:
            raise ValueError(
                "interval_seconds must be at least 1"
            )

        self.interval_seconds = interval_seconds
        self.reminder_service = ReminderService()
        self._running = False

    async def process_due_reminders(self) -> None:
        """
        Find and process all reminders that are currently due.
        """

        reminders = (
            self.reminder_service
            .claim_due_reminders()
        )

        for reminder in reminders:
            reminder_id = reminder["id"]
            user_id = reminder["user_id"]
            title = reminder["title"]

            try:
                # -------------------------------------------------
                # Temporary notification action
                #
                # For now we log/print the reminder.
                # Later this same processor will call the real
                # notification layer (push, WebSocket, voice, etc).
                # -------------------------------------------------
                logger.info(
                    "REMINDER DUE | user=%s | id=%s | title=%s",
                    user_id,
                    reminder_id,
                    title,
                )

                print(
                    f"\n[NOVA REMINDER] "
                    f"user={user_id} "
                    f"id={reminder_id} "
                    f"title={title}\n"
                )

                completed = (
                    self.reminder_service
                    .mark_reminder_completed(
                        reminder_id
                    )
                )

                if not completed:
                    logger.warning(
                        "Could not mark reminder %s as completed.",
                        reminder_id,
                    )

            except Exception:
                logger.exception(
                    "Failed to process reminder %s.",
                    reminder_id,
                )

                # Put it back to pending so it can be retried.
                self.reminder_service.mark_reminder_pending(
                    reminder_id
                )

    async def run(self) -> None:
        """
        Run the scheduler loop until stopped.
        """

        if self._running:
            return

        self._running = True

        logger.info(
            "NOVA reminder scheduler started "
            "(interval=%ss)",
            self.interval_seconds,
        )

        try:
            while self._running:
                await self.process_due_reminders()

                await asyncio.sleep(
                    self.interval_seconds
                )

        finally:
            self._running = False

            logger.info(
                "NOVA reminder scheduler stopped."
            )

    def stop(self) -> None:
        """
        Stop the scheduler loop after the current cycle.
        """

        self._running = False
