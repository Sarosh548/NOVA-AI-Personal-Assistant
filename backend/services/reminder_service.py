from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from database.connection import engine
from models.reminder import Reminder


USER_TIMEZONE = "Asia/Karachi"


class ReminderService:

    def _normalize_datetime(
        self,
        reminder_time: datetime,
    ) -> datetime:
        """
        Normalize a reminder datetime to naive UTC.

        The database stores UTC in a timestamp-without-timezone
        column.
        """

        if reminder_time.tzinfo is None:
            local_timezone = ZoneInfo(
                USER_TIMEZONE
            )

            reminder_time = reminder_time.replace(
                tzinfo=local_timezone
            )

        reminder_time_utc = (
            reminder_time.astimezone(
                timezone.utc
            )
        )

        return reminder_time_utc.replace(
            tzinfo=None
        )

    def create_reminder(
        self,
        user_id: str,
        title: str,
        reminder_time: datetime,
    ) -> int:
        """
        Create a pending reminder.

        The supplied datetime may be timezone-aware.
        The database value is stored as UTC.
        """

        cleaned_title = title.strip()

        if not cleaned_title:
            raise ValueError(
                "Reminder title cannot be empty."
            )

        reminder_time_utc = (
            self._normalize_datetime(
                reminder_time
            )
        )

        if reminder_time_utc <= datetime.utcnow():
            raise ValueError(
                "Reminder time must be in the future."
            )

        with Session(engine) as session:
            reminder = Reminder(
                user_id=user_id,
                title=cleaned_title[:300],
                reminder_time=reminder_time_utc,
                status="pending",
            )

            session.add(reminder)
            session.commit()
            session.refresh(reminder)

            return reminder.id

    def get_pending_reminders(
        self,
        user_id: str,
    ) -> list[dict]:
        """
        Return all pending reminders for a user.
        """

        with Session(engine) as session:
            statement = (
                select(Reminder)
                .where(
                    Reminder.user_id == user_id,
                    Reminder.status == "pending",
                )
                .order_by(
                    Reminder.reminder_time.asc()
                )
            )

            reminders = session.scalars(
                statement
            ).all()

            return [
                {
                    "id": reminder.id,
                    "title": reminder.title,
                    "reminder_time": reminder.reminder_time,
                    "status": reminder.status,
                }
                for reminder in reminders
            ]

    def claim_due_reminders(self) -> list[dict]:
        """
        Atomically claim due reminders.

        A reminder moves from:
            pending -> processing

        This prevents the same reminder from being picked up
        repeatedly by the scheduler while it is being processed.

        PostgreSQL is used here intentionally because NOVA already
        uses PostgreSQL.
        """

        current_time = datetime.utcnow()

        with Session(engine) as session:

            rows = session.execute(
                text(
                    """
                    UPDATE reminders
                    SET status = 'processing',
                        updated_at = :updated_at
                    WHERE status = 'pending'
                      AND reminder_time <= :current_time
                    RETURNING
                        id,
                        user_id,
                        title,
                        reminder_time,
                        status
                    """
                ),
                {
                    "updated_at": current_time,
                    "current_time": current_time,
                },
            ).mappings().all()

            session.commit()

            return [dict(row) for row in rows]

    def mark_reminder_completed(
        self,
        reminder_id: int,
    ) -> bool:
        """
        Mark a processing reminder as completed.
        """

        with Session(engine) as session:
            result = session.execute(
                text(
                    """
                    UPDATE reminders
                    SET status = 'completed',
                        updated_at = :updated_at
                    WHERE id = :reminder_id
                      AND status = 'processing'
                    """
                ),
                {
                    "updated_at": datetime.utcnow(),
                    "reminder_id": reminder_id,
                },
            )

            session.commit()

            return result.rowcount == 1

    def mark_reminder_pending(
        self,
        reminder_id: int,
    ) -> bool:
        """
        Return a processing reminder to pending.

        Useful when notification delivery fails.
        """

        with Session(engine) as session:
            result = session.execute(
                text(
                    """
                    UPDATE reminders
                    SET status = 'pending',
                        updated_at = :updated_at
                    WHERE id = :reminder_id
                      AND status = 'processing'
                    """
                ),
                {
                    "updated_at": datetime.utcnow(),
                    "reminder_id": reminder_id,
                },
            )

            session.commit()

            return result.rowcount == 1

    def get_due_reminders(self) -> list[dict]:
        """
        Compatibility helper.

        Returns due pending reminders without claiming them.
        The scheduler should prefer claim_due_reminders().
        """

        current_time = datetime.utcnow()

        with Session(engine) as session:
            statement = (
                select(Reminder)
                .where(
                    Reminder.status == "pending",
                    Reminder.reminder_time <= current_time,
                )
                .order_by(
                    Reminder.reminder_time.asc()
                )
            )

            reminders = session.scalars(
                statement
            ).all()

            return [
                {
                    "id": reminder.id,
                    "user_id": reminder.user_id,
                    "title": reminder.title,
                    "reminder_time": reminder.reminder_time,
                    "status": reminder.status,
                }
                for reminder in reminders
            ]

    def complete_reminder(
        self,
        reminder_id: int,
        user_id: str,
    ) -> bool:
        """
        Mark a user's reminder as completed.
        """

        with Session(engine) as session:
            reminder = session.scalar(
                select(Reminder).where(
                    Reminder.id == reminder_id,
                    Reminder.user_id == user_id,
                )
            )

            if not reminder:
                return False

            reminder.status = "completed"
            reminder.updated_at = datetime.utcnow()

            session.commit()

            return True

    def cancel_reminder(
        self,
        reminder_id: int,
        user_id: str,
    ) -> bool:
        """
        Cancel a user's reminder.
        """

        with Session(engine) as session:
            reminder = session.scalar(
                select(Reminder).where(
                    Reminder.id == reminder_id,
                    Reminder.user_id == user_id,
                )
            )

            if not reminder:
                return False

            reminder.status = "cancelled"
            reminder.updated_at = datetime.utcnow()

            session.commit()

            return True

    def delete_reminder(
        self,
        reminder_id: int,
        user_id: str,
    ) -> bool:
        """
        Permanently delete a user's reminder.
        """

        with Session(engine) as session:
            reminder = session.scalar(
                select(Reminder).where(
                    Reminder.id == reminder_id,
                    Reminder.user_id == user_id,
                )
            )

            if not reminder:
                return False

            session.delete(reminder)
            session.commit()

            return True
