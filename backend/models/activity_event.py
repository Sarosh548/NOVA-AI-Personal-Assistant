from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


def _utc_now_naive() -> datetime:
    """
    Return current UTC time as naive datetime.

    NOVA currently stores database timestamps as naive UTC.
    """
    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )


class ActivityEvent(Base):
    """
    Durable activity/event record for NOVA.

    Activity events are the source of truth for:
    - workflow activity
    - background operations
    - tool activity
    - notifications
    - future email/messaging/web events
    - proactive daily reports

    This model records what happened; it does not perform
    any operation itself.
    """

    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    conversation_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )

    workflow_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="info",
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    event_metadata: Mapped[dict] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_utc_now_naive,
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_activity_events_user_created",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_activity_events_user_type_created",
            "user_id",
            "event_type",
            "created_at",
        ),
        Index(
            "ix_activity_events_workflow_created",
            "workflow_id",
            "created_at",
        ),
    )