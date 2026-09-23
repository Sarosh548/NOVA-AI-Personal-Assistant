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
    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )


def _generate_lease_id() -> str:
    return str(uuid4())


class VoiceSessionLease(Base):
    """
    Durable ownership lease for one authenticated realtime voice session.

    One user can hold at most one active lease. The lease expires
    automatically when a worker stops heartbeating, allowing a later
    connection to recover without an in-memory dependency.
    """

    __tablename__ = "voice_session_leases"

    id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        default=_generate_lease_id,
    )

    user_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    lease_until: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime,
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

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            name="uq_voice_session_leases_user",
        ),
        Index(
            "ix_voice_session_leases_lease_until",
            "lease_until",
        ),
    )
