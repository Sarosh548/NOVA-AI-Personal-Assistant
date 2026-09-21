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


def _generate_refresh_token_history_id() -> str:
    """
    Generate an opaque UUID-based refresh-token history ID.
    """
    return str(uuid4())


class RefreshTokenHistory(Base):
    """
    Durable lineage record for a refresh token that has been
    successfully rotated.

    Only token hashes are stored. The raw refresh token is never
    persisted. A previously used token can therefore be
    identified and treated as a replay if it appears again.
    """

    __tablename__ = "refresh_token_history"

    __table_args__ = (
        Index(
            "ix_refresh_token_history_session_id",
            "session_id",
        ),
        Index(
            "ix_refresh_token_history_replaced_at",
            "replaced_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        default=_generate_refresh_token_history_id,
    )

    session_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey(
            "sessions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    token_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )

    replaced_by_token_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    replaced_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utc_now_naive,
    )
