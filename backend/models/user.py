from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


def _utc_now_naive() -> datetime:
    """
    Return the current UTC time as a naive datetime.

    NOVA currently stores database timestamps as naive UTC
    datetimes, so timezone-aware UTC time is converted back
    to a naive datetime for database consistency.
    """

    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )


def _generate_user_id() -> str:
    """
    Generate an opaque UUID-based NOVA user ID.

    The value is stored as a string so it remains compatible
    with NOVA's existing user_id columns.
    """

    return str(uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        default=_generate_user_id,
    )

    display_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
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
