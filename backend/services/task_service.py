import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.connection import engine
from models.task import Task


VALID_STATUSES = {
    "pending",
    "in_progress",
    "completed",
    "cancelled",
}

VALID_PRIORITIES = {
    "low",
    "medium",
    "high",
}


def _sanitize_task_title(title: str) -> str:
    """Remove an appended natural-language due-date instruction from a title."""
    cleaned = " ".join(str(title or "").split())
    trailing_instruction_patterns = (
        r"\s+(?:(?:ko|koi)\s+)?due\s+date\s+(?:mat\s+lagana|na\s+lagana)(?:\s+hai)?\.?$",
        r"\s+(?:do\s+not|don't|dont|never)\s+(?:set|add|assign)\s+(?:a\s+)?due\s+date(?:\s+to\s+(?:this\s+task|it))?\.?$",
    )
    for pattern in trailing_instruction_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).rstrip()
    return cleaned


class TaskService:

    def _utc_now_naive(self) -> datetime:
        """
        Return the current UTC time as a naive datetime.

        Task timestamps in the current database are stored as
        naive UTC datetimes, so timezone-aware UTC time is
        converted back to a naive datetime for consistency.
        """

        return datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    def _normalize_datetime(
        self,
        task_time: datetime,
    ) -> datetime:
        """
        Normalize task datetime to naive UTC.

        Database task.due_at is stored as a naive datetime,
        so timezone-aware input is converted to UTC and then
        stripped of timezone information.
        """

        if task_time.tzinfo is None:
            return task_time

        task_time_utc = task_time.astimezone(
            timezone.utc
        )

        return task_time_utc.replace(
            tzinfo=None
        )

    def create_task(
        self,
        user_id: str,
        title: str,
        description: str | None = None,
        priority: str = "medium",
        due_at: datetime | None = None,
    ) -> int:

        cleaned_title = _sanitize_task_title(title)

        if not cleaned_title:
            raise ValueError(
                "Task title cannot be empty."
            )

        # Never silently truncate user-authored task titles. If a title
        # cannot fit the database's 300-character column, fail explicitly
        # so callers cannot report success for a different saved title.
        if len(cleaned_title) > 300:
            raise ValueError(
                "Task title cannot exceed 300 characters."
            )

        if priority not in VALID_PRIORITIES:
            raise ValueError(
                "Invalid task priority."
            )

        normalized_due_at = None

        if due_at is not None:
            normalized_due_at = (
                self._normalize_datetime(
                    due_at
                )
            )

            if normalized_due_at <= self._utc_now_naive():
                raise ValueError(
                    "Task due time must be in the future."
                )

        task = Task(
            user_id=user_id,
            title=cleaned_title,
            description=(
                description.strip()
                if description
                else None
            ),
            status="pending",
            priority=priority,
            due_at=normalized_due_at,
        )

        with Session(engine) as session:
            session.add(task)
            session.commit()
            session.refresh(task)

            return task.id

    def get_tasks(
        self,
        user_id: str,
        status: str | None = None,
    ) -> list[dict]:

        if status is not None:
            if status not in VALID_STATUSES:
                raise ValueError(
                    "Invalid task status."
                )

        with Session(engine) as session:
            statement = (
                select(Task)
                .where(
                    Task.user_id == user_id
                )
                .order_by(
                    Task.due_at.asc().nullslast(),
                    Task.created_at.desc(),
                )
            )

            if status is not None:
                statement = statement.where(
                    Task.status == status
                )

            tasks = session.scalars(
                statement
            ).all()

            return [
                {
                    "id": task.id,
                    "title": task.title,
                    "description": task.description,
                    "status": task.status,
                    "priority": task.priority,
                    "due_at": task.due_at,
                    "created_at": task.created_at,
                    "updated_at": task.updated_at,
                }
                for task in tasks
            ]

    def _normalize_task_text(
        self,
        text: str,
    ) -> set[str]:
        """
        Normalize a natural-language task reference.

        Generic assistant words are removed so phrases such as:

            "my LangGraph practice task"
            "practice LangGraph"

        resolve to the same meaningful tokens.
        """

        generic_words = {
            "a",
            "an",
            "the",
            "my",
            "me",
            "to",
            "please",
            "task",
            "tasks",
            "job",
            "work",
            "one",
            "this",
            "that",
        }

        words = re.findall(
            r"[a-z0-9]+",
            text.lower(),
        )

        return {
            word
            for word in words
            if word not in generic_words
        }

    def find_matching_tasks(
        self,
        user_id: str,
        reference: str,
    ) -> list[dict]:
        """
        Find actionable tasks using a natural-language reference.

        Matching priority:

        1. Exact normalized phrase match
        2. Strong phrase containment match
        3. Token-overlap fallback

        If a strong match exists, weak fallback matches are
        ignored.

        This prevents:

            "practice Docker for my AI Engineer interview"

        from matching both Docker and FastAPI tasks.

        However, a broad reference such as:

            "AI Engineer interview"

        can still return multiple candidates when genuinely
        ambiguous.
        """

        cleaned_reference = reference.strip()

        if not cleaned_reference:
            return []

        reference_tokens = (
            self._normalize_task_text(
                cleaned_reference
            )
        )

        if not reference_tokens:
            return []

        def normalize_phrase(
            text: str,
        ) -> str:
            """
            Normalize text while preserving word order.
            """

            words = re.findall(
                r"[a-z0-9]+",
                text.lower(),
            )

            generic_words = {
                "a",
                "an",
                "the",
                "my",
                "me",
                "to",
                "please",
                "task",
                "tasks",
                "job",
                "work",
                "one",
                "this",
                "that",
            }

            meaningful_words = [
                word
                for word in words
                if word not in generic_words
            ]

            return " ".join(
                meaningful_words
            )

        normalized_reference = (
            normalize_phrase(
                cleaned_reference
            )
        )

        with Session(engine) as session:
            statement = (
                select(Task)
                .where(
                    Task.user_id == user_id,
                    Task.status.in_(
                        [
                            "pending",
                            "in_progress",
                        ]
                    ),
                )
                .order_by(
                    Task.created_at.desc()
                )
            )

            tasks = session.scalars(
                statement
            ).all()

        strong_matches = []
        fallback_matches = []

        for task in tasks:
            normalized_title = (
                normalize_phrase(
                    task.title
                )
            )

            title_tokens = (
                self._normalize_task_text(
                    task.title
                )
            )

            if (
                not normalized_title
                or not title_tokens
            ):
                continue

            # ---------------------------------------------
            # Level 1:
            # Exact normalized phrase
            # ---------------------------------------------

            if (
                normalized_reference
                == normalized_title
            ):
                score = 1.00

            # ---------------------------------------------
            # Level 2:
            # Full normalized reference inside title
            # ---------------------------------------------

            elif (
                normalized_reference
                and normalized_reference
                in normalized_title
            ):
                score = 0.95

            else:
                # -----------------------------------------
                # Level 3:
                # Token-overlap fallback
                # -----------------------------------------

                overlap = (
                    reference_tokens
                    & title_tokens
                )

                union = (
                    reference_tokens
                    | title_tokens
                )

                score = (
                    len(overlap)
                    / len(union)
                    if union
                    else 0.0
                )

            match = {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "status": task.status,
                "priority": task.priority,
                "due_at": task.due_at,
                "_match_score": score,
            }

            if score >= 0.95:
                strong_matches.append(
                    match
                )

            elif score >= 0.50:
                fallback_matches.append(
                    match
                )

        # ---------------------------------------------
        # Strong match wins.
        # ---------------------------------------------

        if strong_matches:
            matches = strong_matches
        else:
            matches = fallback_matches

        matches.sort(
            key=lambda item: (
                item["_match_score"],
                item["id"],
            ),
            reverse=True,
        )

        for match in matches:
            match.pop(
                "_match_score",
                None,
            )

        return matches

    def update_task(
        self,
        task_id: int,
        user_id: str,
        priority: str | None = None,
        due_at: datetime | None = None,
    ) -> bool:
        """
        Update mutable task fields.

        At least one of priority or due_at must be supplied.
        """

        if (
            priority is None
            and due_at is None
        ):
            raise ValueError(
                "No task fields were provided for update."
            )

        if priority is not None:
            if priority not in VALID_PRIORITIES:
                raise ValueError(
                    "Invalid task priority."
                )

        normalized_due_at = None

        if due_at is not None:
            normalized_due_at = (
                self._normalize_datetime(
                    due_at
                )
            )

            if normalized_due_at <= self._utc_now_naive():
                raise ValueError(
                    "Task due time must be in the future."
                )

        with Session(engine) as session:
            task = session.scalar(
                select(Task).where(
                    Task.id == task_id,
                    Task.user_id == user_id,
                )
            )

            if not task:
                return False

            if priority is not None:
                task.priority = priority

            if normalized_due_at is not None:
                task.due_at = normalized_due_at

            task.updated_at = (
                self._utc_now_naive()
            )

            session.commit()

            return True

    def complete_task(
        self,
        task_id: int,
        user_id: str,
    ) -> bool:

        with Session(engine) as session:
            task = session.scalar(
                select(Task).where(
                    Task.id == task_id,
                    Task.user_id == user_id,
                )
            )

            if not task:
                return False

            task.status = "completed"
            task.updated_at = (
                self._utc_now_naive()
            )

            session.commit()

            return True

    def start_task(
        self,
        task_id: int,
        user_id: str,
    ) -> bool:

        with Session(engine) as session:
            task = session.scalar(
                select(Task).where(
                    Task.id == task_id,
                    Task.user_id == user_id,
                )
            )

            if not task:
                return False

            task.status = "in_progress"
            task.updated_at = (
                self._utc_now_naive()
            )

            session.commit()

            return True

    def cancel_task(
        self,
        task_id: int,
        user_id: str,
    ) -> bool:

        with Session(engine) as session:
            task = session.scalar(
                select(Task).where(
                    Task.id == task_id,
                    Task.user_id == user_id,
                )
            )

            if not task:
                return False

            task.status = "cancelled"
            task.updated_at = (
                self._utc_now_naive()
            )

            session.commit()

            return True

    def delete_task(
        self,
        task_id: int,
        user_id: str,
    ) -> bool:

        with Session(engine) as session:
            task = session.scalar(
                select(Task).where(
                    Task.id == task_id,
                    Task.user_id == user_id,
                )
            )

            if not task:
                return False

            session.delete(task)
            session.commit()

            return True
    def delete_tasks(
        self,
        task_ids: list[int],
        user_id: str,
        expected_status: str | None = None,
    ) -> list[dict]:
        """
        Delete an exact, previously confirmed set of task IDs atomically.

        When expected_status is provided, every task must still have that
        status. If any task is missing, belongs to another user, or changed
        status after confirmation, abort before deleting any task.
        """
        if not isinstance(task_ids, (list, tuple)) or not task_ids:
            raise ValueError("At least one task ID is required for bulk deletion.")

        if expected_status is not None and expected_status not in VALID_STATUSES:
            raise ValueError("Invalid task status.")

        normalized_ids: list[int] = []
        for raw_id in task_ids:
            if isinstance(raw_id, bool):
                raise ValueError("Task IDs must be positive integers.")
            try:
                task_id = int(raw_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("Task IDs must be positive integers.") from exc
            if task_id <= 0:
                raise ValueError("Task IDs must be positive integers.")
            if task_id not in normalized_ids:
                normalized_ids.append(task_id)

        with Session(engine) as session:
            tasks = session.scalars(
                select(Task).where(
                    Task.user_id == user_id,
                    Task.id.in_(normalized_ids),
                )
            ).all()

            tasks_by_id = {task.id: task for task in tasks}
            missing_ids = [
                task_id for task_id in normalized_ids
                if task_id not in tasks_by_id
            ]
            if missing_ids:
                raise ValueError(
                    f"Tasks no longer available for deletion: {missing_ids}."
                )

            if expected_status is not None:
                changed_ids = [
                    task_id
                    for task_id in normalized_ids
                    if tasks_by_id[task_id].status != expected_status
                ]
                if changed_ids:
                    raise ValueError(
                        "Some selected tasks no longer match the confirmed "
                        f"status '{expected_status}': {changed_ids}. "
                        "No tasks were deleted."
                    )

            deleted = [
                {
                    "id": task_id,
                    "title": tasks_by_id[task_id].title,
                    "status": tasks_by_id[task_id].status,
                    "priority": tasks_by_id[task_id].priority,
                }
                for task_id in normalized_ids
            ]
            for task_id in normalized_ids:
                session.delete(tasks_by_id[task_id])
            session.commit()

            return deleted
