import asyncio
import logging
from typing import Any

from services.activity_event_service import (
    ActivityEventService,
)
from services.notification_service import NotificationService
from services.reminder_service import ReminderService


logger = logging.getLogger(__name__)


class ReminderScheduler:
    """
    Lightweight NOVA reminder scheduler.

    It checks PostgreSQL periodically for due reminders,
    claims them atomically, delivers a notification, and
    marks the reminder completed only after successful delivery.

    Durable activity events record meaningful background outcomes.
    Activity recording is best-effort and never changes reminder
    processing behavior.
    """

    def __init__(
        self,
        interval_seconds: int = 5,
        reminder_service: ReminderService | None = None,
        notification_service: NotificationService | None = None,
        activity_event_service: (
            ActivityEventService | None
        ) = None,
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
        self.activity_event_service = (
            activity_event_service
            if activity_event_service is not None
            else ActivityEventService()
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

                    self._record_activity_event(
                        user_id=user_id,
                        event_type=(
                            "reminder_delivery_failed"
                        ),
                        status="failed",
                        title=(
                            "Reminder delivery failed: "
                            f"{str(title)[:150]}"
                        ),
                        summary=(
                            "NOVA could not deliver reminder "
                            f"'{str(title)[:200]}'."
                        ),
                        metadata={
                            "reminder_id": reminder_id,
                            "reminder_time": (
                                reminder.get(
                                    "reminder_time"
                                )
                            ),
                        },
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

                    self._record_activity_event(
                        user_id=user_id,
                        event_type=(
                            "reminder_completion_failed"
                        ),
                        status="partial",
                        title=(
                            "Reminder delivered but "
                            "completion failed: "
                            f"{str(title)[:140]}"
                        ),
                        summary=(
                            "NOVA delivered reminder "
                            f"'{str(title)[:200]}', but the "
                            "reminder could not be marked completed."
                        ),
                        metadata={
                            "reminder_id": reminder_id,
                            "reminder_time": (
                                reminder.get(
                                    "reminder_time"
                                )
                            ),
                        },
                    )

                    continue

                self._record_activity_event(
                    user_id=user_id,
                    event_type="reminder_completed",
                    status="success",
                    title=(
                        "Reminder completed: "
                        f"{str(title)[:150]}"
                    ),
                    summary=(
                        "NOVA delivered and completed "
                        f"reminder '{str(title)[:200]}'."
                    ),
                    metadata={
                        "reminder_id": reminder_id,
                        "reminder_time": (
                            reminder.get(
                                "reminder_time"
                            )
                        ),
                    },
                )

            except Exception as exc:
                logger.exception(
                    "Failed to process reminder %s.",
                    reminder_id,
                )

                self._record_activity_event(
                    user_id=user_id,
                    event_type="reminder_delivery_failed",
                    status="failed",
                    title=(
                        "Reminder processing failed: "
                        f"{str(title)[:150]}"
                    ),
                    summary=(
                        "NOVA could not process reminder "
                        f"'{str(title)[:200]}'."
                    ),
                    metadata={
                        "reminder_id": reminder_id,
                        "error": str(exc),
                        "reminder_time": (
                            reminder.get(
                                "reminder_time"
                            )
                        ),
                    },
                )

                self.reminder_service.mark_reminder_pending(
                    reminder_id
                )

    def _record_activity_event(
        self,
        *,
        user_id: str,
        event_type: str,
        status: str,
        title: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Record one scheduler event without affecting scheduler
        control flow when activity persistence fails.
        """

        try:
            self.activity_event_service.record_event(
                user_id=user_id,
                event_type=event_type,
                source="reminder_scheduler",
                status=status,
                title=title,
                summary=summary,
                metadata=metadata,
            )

        except Exception:
            logger.exception(
                "Failed to record activity event "
                "'%s' for user=%s.",
                event_type,
                user_id,
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