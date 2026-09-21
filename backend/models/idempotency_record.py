from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    Text,
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


class IdempotencyRecord(Base):
    """
    Durable result record for safe retries of synchronous APIs.
    """

    __tablename__ = "idempotency_records"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    endpoint: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    request_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="processing",
    )

    response_status: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    response_body: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    claim_token: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
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

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "endpoint",
            "idempotency_key",
            name="uq_idempotency_request_key",
        ),
        Index(
            "ix_idempotency_status_lease",
            "status",
            "lease_until",
        ),
        Index(
            "ix_idempotency_expires",
            "expires_at",
        ),
        Index(
            "ix_idempotency_user_created",
            "user_id",
            "created_at",
        ),
    )
