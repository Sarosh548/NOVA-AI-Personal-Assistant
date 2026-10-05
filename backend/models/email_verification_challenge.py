from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _generate_id() -> str:
    return str(uuid4())


class EmailVerificationChallenge(Base):
    __tablename__ = "email_verification_challenges"

    id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        default=_generate_id,
    )

    user_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    code_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    code_salt: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    used_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    sent_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utc_now_naive,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utc_now_naive,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utc_now_naive,
        onupdate=_utc_now_naive,
    )

    __table_args__ = (
        Index(
            "ix_email_verification_challenges_user_id",
            "user_id",
        ),
        Index(
            "ix_email_verification_challenges_expires_at",
            "expires_at",
        ),
    )
