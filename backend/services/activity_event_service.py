from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.connection import engine as default_engine
from models.activity_event import ActivityEvent


class ActivityEventService:
    """
    Durable activity/event persistence service.

    Responsibilities:
    - record structured NOVA activity
    - retrieve recent activity for a user
    - filter activity by type/source/time
    - preserve optional conversation/workflow linkage

    This service does NOT:
    - execute tools
    - send notifications
    - make permission decisions
    - generate LLM summaries
    """

    VALID_STATUSES = {
        "info",
        "pending",
        "success",
        "partial",
        "failed",
        "blocked",
    }

    def __init__(
        self,
        db_engine: Any | None = None,
    ):
        self.engine = (
            db_engine
            if db_engine is not None
            else default_engine
        )

    @staticmethod
    def _utc_now_naive() -> datetime:
        return datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    @staticmethod
    def _normalize_datetime(
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None

        if value.tzinfo is None:
            return value

        return value.astimezone(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    @staticmethod
    def _normalize_text(
        value: str,
        *,
        field_name: str,
    ) -> str:
        normalized = str(
            value
        ).strip()

        if not normalized:
            raise ValueError(
                f"Activity event {field_name} cannot be empty."
            )

        return normalized

    @staticmethod
    def _json_safe(
        value: Any,
    ) -> Any:
        if value is None:
            return None

        if isinstance(
            value,
            datetime,
        ):
            return value.isoformat()

        if isinstance(
            value,
            dict,
        ):
            return {
                str(key): ActivityEventService._json_safe(
                    item
                )
                for key, item in value.items()
            }

        if isinstance(
            value,
            (list, tuple),
        ):
            return [
                ActivityEventService._json_safe(
                    item
                )
                for item in value
            ]

        if isinstance(
            value,
            (str, int, float, bool),
        ):
            return value

        return str(value)

    def record_event(
        self,
        *,
        user_id: str,
        event_type: str,
        source: str,
        title: str,
        summary: str,
        status: str = "info",
        conversation_id: int | None = None,
        workflow_id: int | None = None,
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Persist one durable activity event.
        """

        normalized_user_id = (
            self._normalize_text(
                user_id,
                field_name="user_id",
            )
        )

        normalized_event_type = (
            self._normalize_text(
                event_type,
                field_name="event_type",
            ).lower()
        )

        normalized_source = (
            self._normalize_text(
                source,
                field_name="source",
            ).lower()
        )

        normalized_status = (
            self._normalize_text(
                status,
                field_name="status",
            ).lower()
        )

        if normalized_status not in (
            self.VALID_STATUSES
        ):
            raise ValueError(
                "Invalid activity event status."
            )

        normalized_title = (
            self._normalize_text(
                title,
                field_name="title",
            )
        )

        normalized_summary = (
            self._normalize_text(
                summary,
                field_name="summary",
            )
        )

        normalized_created_at = (
            self._normalize_datetime(
                created_at
            )
        )

        if normalized_created_at is None:
            normalized_created_at = (
                self._utc_now_naive()
            )

        event = ActivityEvent(
            user_id=normalized_user_id,
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            event_type=normalized_event_type,
            source=normalized_source,
            status=normalized_status,
            title=normalized_title[:200],
            summary=normalized_summary,
            event_metadata=self._json_safe(
                dict(metadata or {})
            ),
            created_at=normalized_created_at,
        )

        with Session(self.engine) as session:
            session.add(event)
            session.commit()
            session.refresh(event)

            return self._event_to_dict(
                event
            )

    def list_events(
        self,
        *,
        user_id: str,
        limit: int = 100,
        event_type: str | None = None,
        source: str | None = None,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return recent activity events for a user.

        Results are newest-first.
        """

        normalized_user_id = (
            self._normalize_text(
                user_id,
                field_name="user_id",
            )
        )

        normalized_limit = max(
            1,
            min(
                int(limit),
                500,
            ),
        )

        statement = (
            select(ActivityEvent)
            .where(
                ActivityEvent.user_id
                == normalized_user_id
            )
        )

        if event_type is not None:
            statement = statement.where(
                ActivityEvent.event_type
                == str(
                    event_type
                ).strip().lower()
            )

        if source is not None:
            statement = statement.where(
                ActivityEvent.source
                == str(
                    source
                ).strip().lower()
            )

        normalized_since = (
            self._normalize_datetime(
                since
            )
        )

        if normalized_since is not None:
            statement = statement.where(
                ActivityEvent.created_at
                >= normalized_since
            )

        statement = (
            statement
            .order_by(
                ActivityEvent.created_at.desc(),
                ActivityEvent.id.desc(),
            )
            .limit(normalized_limit)
        )

        with Session(self.engine) as session:
            events = session.scalars(
                statement
            ).all()

            return [
                self._event_to_dict(
                    event
                )
                for event in events
            ]

    @staticmethod
    def _event_to_dict(
        event: ActivityEvent,
    ) -> dict[str, Any]:
        return {
            "id": event.id,
            "user_id": event.user_id,
            "conversation_id": event.conversation_id,
            "workflow_id": event.workflow_id,
            "event_type": event.event_type,
            "source": event.source,
            "status": event.status,
            "title": event.title,
            "summary": event.summary,
            "metadata": event.event_metadata,
            "created_at": event.created_at,
        }