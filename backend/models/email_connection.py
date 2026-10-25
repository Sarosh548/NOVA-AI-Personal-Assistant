from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _generate_email_connection_id() -> str:
    return str(uuid4())


class EmailConnection(Base):
    """Per-user Google Mail OAuth connection; tokens are encrypted at rest."""

    __tablename__ = "email_connections"

    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_email_connections_user_provider"),
        Index("ix_email_connections_user_id", "user_id"),
        Index("ix_email_connections_token_expires_at", "token_expires_at"),
        Index("ix_email_connections_token_refresh_lease_until", "token_refresh_lease_until"),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=_generate_email_connection_id)
    user_id: Mapped[str] = mapped_column(String(100), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="google")
    email_address: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    token_refresh_claim_token: Mapped[str | None] = mapped_column(String(100), nullable=True)
    token_refresh_lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scopes: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now_naive, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now_naive, onupdate=_utc_now_naive, nullable=False)
