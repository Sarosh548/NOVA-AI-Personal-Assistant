from datetime import datetime, timezone

from sqlalchemy import (
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
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


class ActivityDigestDelivery(Base):
    """
    Durable delivery state for proactive activity digests.

    One row represents one logical digest delivery slot for:
        user + local date + digest type

    The row allows NOVA to:
    - prevent duplicate successful delivery
    - safely claim work
    - recover from abandoned processing leases
    - retry failed notification delivery
    - expose a stable delivery key to future channels
    """

    __tablename__ = "activity_digest_deliveries"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    digest_date: Mapped[object] = mapped_column(
        Date,
        nullable=False,
    )

    digest_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="daily_activity",
    )

    delivery_key: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
        unique=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="processing",
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    claim_token: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
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

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "digest_date",
            "digest_type",
            name=(
                "uq_activity_digest_delivery_slot"
            ),
        ),
        Index(
            "ix_activity_digest_deliveries_user_date",
            "user_id",
            "digest_date",
        ),
        Index(
            "ix_activity_digest_deliveries_status_lease",
            "status",
            "lease_until",
        ),
    )