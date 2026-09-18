from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
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


class UserNotificationPreferences(Base):
    """
    Durable per-user notification preferences.

    These preferences are independent from notification delivery
    records. Delivery state answers "was this notification delivered?",
    while this model answers "how should this user receive it?"
    """

    __tablename__ = "user_notification_preferences"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    timezone: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="Asia/Karachi",
    )

    daily_activity_digest_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    delivery_hour: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=21,
    )

    delivery_minute: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
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
            name="uq_user_notification_preferences_user",
        ),
    )