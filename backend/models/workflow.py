from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


def _utc_now_naive() -> datetime:
    """
    Return the current UTC time as a naive datetime.

    NOVA currently stores database timestamps as naive UTC.
    """

    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )


class Workflow(Base):
    __tablename__ = "workflows"

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

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        index=True,
    )

    execution_mode: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="workflow",
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        index=True,
    )

    plan: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )

    result: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    claim_token: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_utc_now_naive,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_utc_now_naive,
        onupdate=_utc_now_naive,
        nullable=False,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_workflows_user_idempotency",
        ),
        Index(
            "ix_workflows_user_status_created",
            "user_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_workflows_autonomous_due",
            "execution_mode",
            "status",
            "scheduled_at",
        ),
        Index(
            "ix_workflows_lease_recovery",
            "execution_mode",
            "status",
            "lease_until",
        ),
    )