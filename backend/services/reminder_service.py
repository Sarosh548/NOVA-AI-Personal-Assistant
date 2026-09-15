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

        reminder_time_utc = reminder_time.astimezone(
            timezone.utc
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

    def find_matching_reminders(
        self,
        user_id: str,
        reference: str,
    ) -> list[dict]:
        """
        Find active reminders using a natural-language reference.

        Matching is based on meaningful title tokens.
        Multiple matches are returned so the caller can avoid
        making an unsafe guess.
        """

        cleaned_reference = reference.strip()

        if not cleaned_reference:
            return []

        generic_words = {
            "a",
            "an",
            "the",
            "my",
            "me",
            "to",
            "please",
            "reminder",
            "reminders",
            "this",
            "that",
            "one",
        }

        reference_tokens = {
            word
            for word in cleaned_reference.lower().split()
            if word not in generic_words
        }

        if not reference_tokens:
            return []

        with Session(engine) as session:
            statement = (
                select(Reminder)
                .where(
                    Reminder.user_id == user_id,
                    Reminder.status.in_(
                        ["pending", "processing"]
                    ),
                )
                .order_by(
                    Reminder.created_at.desc()
                )
            )

            reminders = session.scalars(
                statement
            ).all()

        matches = []

        for reminder in reminders:
            title_tokens = {
                word
                for word in reminder.title.lower().split()
                if word not in generic_words
            }

            if not title_tokens:
                continue

            overlap = reference_tokens & title_tokens

            if reference_tokens == title_tokens:
                score = 1.0

            elif (
                reference_tokens.issubset(
                    title_tokens
                )
                or title_tokens.issubset(
                    reference_tokens
                )
            ):
                score = 0.90

            else:
                union = (
                    reference_tokens | title_tokens
                )

                score = (
                    len(overlap) / len(union)
                    if union
                    else 0.0
                )

            if score >= 0.50:
                matches.append(
                    {
                        "id": reminder.id,
                        "title": reminder.title,
                        "reminder_time": reminder.reminder_time,
                        "status": reminder.status,
                        "_match_score": score,
                    }
                )

        matches.sort(
            key=lambda item: (
                item["_match_score"],
                item["id"],
            ),
            reverse=True,
        )

        for match in matches:
            match.pop("_match_score", None)

        return matches

    def update_reminder(
        self,
        reminder_id: int,
        user_id: str,
        title: str | None = None,
        reminder_time: datetime | None = None,
    ) -> bool:
        """
        Update an existing reminder's title and/or time.
        """

        if title is None and reminder_time is None:
            raise ValueError(
                "No reminder fields were provided for update."
            )

        cleaned_title = None

        if title is not None:
            cleaned_title = title.strip()

            if not cleaned_title:
                raise ValueError(
                    "Reminder title cannot be empty."
                )

        normalized_time = None

        if reminder_time is not None:
            normalized_time = (
                self._normalize_datetime(
                    reminder_time
                )
            )

            if normalized_time <= datetime.utcnow():
                raise ValueError(
                    "Reminder time must be in the future."
                )

        with Session(engine) as session:
            reminder = session.scalar(
                select(Reminder).where(
                    Reminder.id == reminder_id,
                    Reminder.user_id == user_id,
                )
            )

            if not reminder:
                return False

            if cleaned_title is not None:
                reminder.title = cleaned_title[:300]

            if normalized_time is not None:
                reminder.reminder_time = normalized_time

            reminder.updated_at = datetime.utcnow()

            session.commit()

            return True

    def claim_due_reminders(self) -> list[dict]:
        """
        Atomically claim due reminders.

        pending -> processing
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