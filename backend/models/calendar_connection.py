from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


def _utc_now_naive() -> datetime:
    """
    Return the current UTC time as a naive datetime.

    NOVA stores database timestamps as naive UTC values for
    consistency with the existing persistence layer.
    """
    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )


def _generate_connection_id() -> str:
    """
    Generate an opaque UUID-based calendar connection ID.
    """
    return str(uuid4())


class CalendarConnection(Base):
    """
    Durable external calendar connection for one NOVA user.

    Provider credentials are stored separately from NOVA's local
    authentication identity. OAuth access and refresh tokens are
    encrypted at rest by the application service layer.

    Current provider:
    - google
    """

    __tablename__ = "calendar_connections"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider",
            name="uq_calendar_connections_user_provider",
        ),
        Index(
            "ix_calendar_connections_user_id",
            "user_id",
        ),
        Index(
            "ix_calendar_connections_token_expires_at",
            "token_expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        default=_generate_connection_id,
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

    calendar_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="primary",
    )

    encrypted_access_token: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    encrypted_refresh_token: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    token_refresh_claim_token: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    token_refresh_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    scopes: Mapped[str] = mapped_column(
        Text,
        nullable=False,
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
