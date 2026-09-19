from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
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


def _generate_session_id() -> str:
    """
    Generate an opaque UUID-based session ID.
    """
    return str(uuid4())


class UserSession(Base):
    """
    Represents one authenticated NOVA client session.

    Refresh tokens are never stored in plaintext. The
    refresh_token_hash field stores only the server-side hash
    that will later be used for rotation and replay protection.
    """

    __tablename__ = "sessions"

    __table_args__ = (
        Index(
            "ix_sessions_user_id",
            "user_id",
        ),
        Index(
            "ix_sessions_expires_at",
            "expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        default=_generate_session_id,
    )

    user_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    refresh_token_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
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
