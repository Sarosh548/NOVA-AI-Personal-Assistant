from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from database.connection import engine as default_engine
from models.reminder import Reminder


USER_TIMEZONE = "Asia/Karachi"


class ReminderService:
    CLAIM_LEASE_SECONDS = 300

    def __init__(self, engine=None):
        self.engine = (
            engine
            if engine is not None
            else default_engine
        )

    @staticmethod
    def _utc_now_naive() -> datetime:
        return datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

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

        if reminder_time_utc <= self._utc_now_naive():
            raise ValueError(
                "Reminder time must be in the future."
            )

        with Session(self.engine) as session:
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

        with Session(self.engine) as session:
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

        with Session(self.engine) as session:
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

            if normalized_time <= self._utc_now_naive():
                raise ValueError(
                    "Reminder time must be in the future."
                )

        with Session(self.engine) as session:
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

            reminder.updated_at = self._utc_now_naive()

            session.commit()

            return True

    def claim_due_reminders(
        self,
        *,
        now: datetime | None = None,
    ) -> list[dict]:
        """
        Atomically claim due or stale-processing reminders.

        pending + due -> processing
        processing + expired lease -> processing with a new lease

        Every claim receives a unique token so a worker that loses
        its lease cannot finalize the reminder later.
        """

        current_time = (
            now
            if now is not None
            else self._utc_now_naive()
        )

        if current_time.tzinfo is not None:
            current_time = (
                current_time.astimezone(
                    timezone.utc
                ).replace(
                    tzinfo=None
                )
            )

        lease_until = (
            current_time
            + timedelta(
                seconds=self.CLAIM_LEASE_SECONDS
            )
        )

        claimable = select(Reminder).where(
            or_(
                and_(
                    Reminder.status == "pending",
                    Reminder.reminder_time
                    <= current_time,
                ),
                and_(
                    Reminder.status == "processing",
                    or_(
                        Reminder.lease_until.is_(None),
                        Reminder.lease_until
                        <= current_time,
                    ),
                ),
            )
        ).order_by(
            Reminder.reminder_time.asc(),
            Reminder.id.asc(),
        ).with_for_update(
            skip_locked=True
        )

        with Session(self.engine) as session:
            reminders = session.scalars(
                claimable
            ).all()

            claimed: list[dict] = []

            for reminder in reminders:
                claim_token = uuid4().hex

                reminder.status = "processing"
                reminder.claim_token = claim_token
                reminder.lease_until = lease_until
                reminder.updated_at = current_time

                claimed.append(
                    {
                        "id": reminder.id,
                        "user_id": reminder.user_id,
                        "title": reminder.title,
                        "reminder_time": (
                            reminder.reminder_time
                        ),
                        "status": reminder.status,
                        "claim_token": claim_token,
                        "lease_until": lease_until,
                    }
                )

            session.commit()

            return claimed

    def mark_reminder_completed(
        self,
        reminder_id: int,
        *,
        claim_token: str,
    ) -> bool:
        """
        Complete a reminder only when the worker still owns its lease.
        """

        normalized_token = str(
            claim_token
        ).strip()

        if not normalized_token:
            raise ValueError(
                "claim_token cannot be empty."
            )

        now = self._utc_now_naive()

        with Session(self.engine) as session:
            result = session.execute(
                update(Reminder)
                .where(
                    Reminder.id == reminder_id,
                    Reminder.status == "processing",
                    Reminder.claim_token
                    == normalized_token,
                    Reminder.lease_until.is_not(None),
                    Reminder.lease_until > now,
                )
                .values(
                    status="completed",
                    claim_token=None,
                    lease_until=None,
                    updated_at=now,
                )
            )

            session.commit()

            return result.rowcount == 1

    def mark_reminder_pending(
        self,
        reminder_id: int,
        *,
        claim_token: str,
    ) -> bool:
        """
        Return a failed reminder to pending only when the worker still
        owns its lease.
        """

        normalized_token = str(
            claim_token
        ).strip()

        if not normalized_token:
            raise ValueError(
                "claim_token cannot be empty."
            )

        now = self._utc_now_naive()

        with Session(self.engine) as session:
            result = session.execute(
                update(Reminder)
                .where(
                    Reminder.id == reminder_id,
                    Reminder.status == "processing",
                    Reminder.claim_token
                    == normalized_token,
                    Reminder.lease_until.is_not(None),
                    Reminder.lease_until > now,
                )
                .values(
                    status="pending",
                    claim_token=None,
                    lease_until=None,
                    updated_at=now,
                )
            )

            session.commit()

            return result.rowcount == 1

    def get_due_reminders(self) -> list[dict]:
        """
        Compatibility helper.
        """

        current_time = self._utc_now_naive()

        with Session(self.engine) as session:
            statement = (
                select(Reminder)
                .where(
                    Reminder.status == "pending",
                    Reminder.reminder_time
                    <= current_time,
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

        with Session(self.engine) as session:
            reminder = session.scalar(
                select(Reminder).where(
                    Reminder.id == reminder_id,
                    Reminder.user_id == user_id,
                )
            )

            if not reminder:
                return False

            reminder.status = "completed"
            reminder.claim_token = None
            reminder.lease_until = None
            reminder.updated_at = self._utc_now_naive()

            session.commit()

            return True

    def cancel_reminder(
        self,
        reminder_id: int,
        user_id: str,
    ) -> bool:

        with Session(self.engine) as session:
            reminder = session.scalar(
                select(Reminder).where(
                    Reminder.id == reminder_id,
                    Reminder.user_id == user_id,
                )
            )

            if not reminder:
                return False

            reminder.status = "cancelled"
            reminder.claim_token = None
            reminder.lease_until = None
            reminder.updated_at = self._utc_now_naive()

            session.commit()

            return True

    def delete_reminder(
        self,
        reminder_id: int,
        user_id: str,
    ) -> bool:

        with Session(self.engine) as session:
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
