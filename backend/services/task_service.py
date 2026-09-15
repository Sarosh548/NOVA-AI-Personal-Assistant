import re
from datetime import datetime

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


class TaskService:

    def create_task(
        self,
        user_id: str,
        title: str,
        description: str | None = None,
        priority: str = "medium",
        due_at: datetime | None = None,
    ) -> int:
        cleaned_title = title.strip()

        if not cleaned_title:
            raise ValueError(
                "Task title cannot be empty."
            )

        if priority not in VALID_PRIORITIES:
            raise ValueError(
                "Invalid task priority."
            )

        if due_at is not None:
            if due_at <= datetime.utcnow():
                raise ValueError(
                    "Task due time must be in the future."
                )

        task = Task(
            user_id=user_id,
            title=cleaned_title[:300],
            description=(
                description.strip()
                if description
                else None
            ),
            status="pending",
            priority=priority,
            due_at=due_at,
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
                .where(Task.user_id == user_id)
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

        Matching is performed against active tasks only.

        The reference and title are normalized into meaningful
        tokens so word-order differences and generic words do
        not prevent a valid match.

        If multiple tasks match, the caller can ask the user
        for clarification instead of guessing.
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

        with Session(engine) as session:
            statement = (
                select(Task)
                .where(
                    Task.user_id == user_id,
                    Task.status.in_(
                        ["pending", "in_progress"]
                    ),
                )
                .order_by(
                    Task.created_at.desc()
                )
            )

            tasks = session.scalars(
                statement
            ).all()

        matches = []

        for task in tasks:
            title_tokens = (
                self._normalize_task_text(
                    task.title
                )
            )

            if not title_tokens:
                continue

            overlap = (
                reference_tokens
                & title_tokens
            )

            # Exact normalized match.
            if reference_tokens == title_tokens:
                score = 1.0

            # One side completely identifies the other.
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
                    reference_tokens
                    | title_tokens
                )

                score = (
                    len(overlap) / len(union)
                    if union
                    else 0.0
                )

            # Require meaningful overlap.
            if score >= 0.50:
                matches.append(
                    {
                        "id": task.id,
                        "title": task.title,
                        "description": task.description,
                        "status": task.status,
                        "priority": task.priority,
                        "due_at": task.due_at,
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

        # Internal score should never leak to callers.
        for match in matches:
            match.pop("_match_score", None)

        return matches

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
            task.updated_at = datetime.utcnow()

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
            task.updated_at = datetime.utcnow()

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
            task.updated_at = datetime.utcnow()

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