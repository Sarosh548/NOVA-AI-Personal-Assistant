from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


def _utc_now_naive() -> datetime:
    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )


class RateLimitCounter(Base):
    """
    Durable fixed-window request counter.

    A single row is maintained per principal and scope so the table
    stays bounded while concurrent requests can update the counter
    atomically at the database layer.
    """

    __tablename__ = "rate_limit_counters"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    principal_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    scope: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    window_start: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    request_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_utc_now_naive,
        onupdate=_utc_now_naive,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "principal_key",
            "scope",
            name="uq_rate_limit_principal_scope",
        ),
        Index(
            "ix_rate_limit_scope_window",
            "scope",
            "window_start",
        ),
    )
