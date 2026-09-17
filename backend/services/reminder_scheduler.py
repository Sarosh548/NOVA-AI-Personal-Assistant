import asyncio
import logging

from services.notification_service import NotificationService
from services.reminder_service import ReminderService


logger = logging.getLogger(__name__)


class ReminderScheduler:
    """
    Lightweight NOVA reminder scheduler.

    It checks PostgreSQL periodically for due reminders,
    claims them atomically, delivers a notification, and
    marks the reminder completed only after successful delivery.
    """

    def __init__(
        self,
        interval_seconds: int = 5,
        reminder_service: ReminderService | None = None,
        notification_service: NotificationService | None = None,
    ):
        if interval_seconds < 1:
            raise ValueError(
                "interval_seconds must be at least 1"
            )

        self.interval_seconds = interval_seconds
        self.reminder_service = (
            reminder_service
            if reminder_service is not None
            else ReminderService()
        )
        self.notification_service = (
            notification_service
            if notification_service is not None
            else NotificationService()
        )
        self._running = False

    async def process_due_reminders(self) -> None:
        """
        Find and process all reminders that are currently due.

        A reminder is completed only after the notification
        service confirms successful delivery.
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
                delivered = (
                    self.notification_service.notify(
                        user_id=user_id,
                        title="NOVA Reminder",
                        body=title,
                        notification_type="reminder",
                        metadata={
                            "reminder_id": reminder_id,
                        },
                    )
                )

                if not delivered:
                    logger.warning(
                        "Notification delivery failed "
                        "for reminder %s.",
                        reminder_id,
                    )

                    self.reminder_service.mark_reminder_pending(
                        reminder_id
                    )

                    continue

                completed = (
                    self.reminder_service
                    .mark_reminder_completed(
                        reminder_id
                    )
                )

                if not completed:
                    logger.warning(
                        "Could not mark reminder %s as completed "
                        "after successful notification.",
                        reminder_id,
                    )

            except Exception:
                logger.exception(
                    "Failed to process reminder %s.",
                    reminder_id,
                )

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