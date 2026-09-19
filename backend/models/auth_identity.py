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

    NOVA currently stores database timestamps as naive UTC
    datetimes, so timezone-aware UTC time is converted back
    to a naive datetime for database consistency.
    """
    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )


def _generate_auth_identity_id() -> str:
    """
    Generate an opaque UUID-based auth identity ID.
    """
    return str(uuid4())


class AuthIdentity(Base):
    """
    Authentication identity linked to a canonical NOVA User.

    Authentication mechanisms are intentionally separated from
    the core User model so future providers such as Google,
    Apple, and OIDC can be added without changing User itself.
    """

    __tablename__ = "auth_identities"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider",
            name="uq_auth_identities_user_provider",
        ),
        UniqueConstraint(
            "provider",
            "provider_subject",
            name="uq_auth_identities_provider_subject",
        ),
        Index(
            "ix_auth_identities_user_id",
            "user_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        default=_generate_auth_identity_id,
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

    provider_subject: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    password_hash: Mapped[str | None] = mapped_column(
        String(512),
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
