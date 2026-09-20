from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


def _utc_now_naive() -> datetime:
    """
    Return the current UTC time as a naive datetime.
    """
    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )


def _generate_oauth_state_id() -> str:
    """
    Generate an opaque UUID-based OAuth state record ID.
    """
    return str(uuid4())


class OAuthState(Base):
    """
    One-time server-side OAuth state bound to a NOVA user.

    Only a SHA-256 hash of the browser-visible state value is stored.
    The plaintext state is returned only to the authorization client.
    """

    __tablename__ = "oauth_states"

    __table_args__ = (
        UniqueConstraint(
            "state_hash",
            name="uq_oauth_states_state_hash",
        ),
        Index(
            "ix_oauth_states_user_provider",
            "user_id",
            "provider",
        ),
        Index(
            "ix_oauth_states_expires_at",
            "expires_at",
        ),
        Index(
            "ix_oauth_states_used_at",
            "used_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        default=_generate_oauth_state_id,
    )

    user_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    state_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    used_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_utc_now_naive,
        nullable=False,
    )
