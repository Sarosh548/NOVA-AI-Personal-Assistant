from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
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


class NotificationDestination(Base):
    """
    Durable destination for one user's outbound notifications.

    Destination addresses are user-scoped and separate from provider
    credentials. Provider credentials remain server-side configuration.

    Current destination-capable channel:
    - email

    Future channels can reuse this model:
    - whatsapp
    - sms
    - push
    - other provider-backed channels
    """

    __tablename__ = "notification_destinations"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    channel: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    destination: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    label: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
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
            "channel",
            "destination",
            name=(
                "uq_notification_destinations_user_channel_destination"
            ),
        ),
        Index(
            "ix_notification_destinations_user_channel",
            "user_id",
            "channel",
        ),
        Index(
            "ix_notification_destinations_user_enabled",
            "user_id",
            "is_enabled",
        ),
        Index(
            "ix_notification_destinations_user_channel_default",
            "user_id",
            "channel",
            "is_default",
        ),
    )