from datetime import datetime, timezone

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


def _utc_now_naive() -> datetime:
    """
    Return current UTC time as a naive datetime for NOVA's
    existing naive-UTC database timestamp columns.
    """

    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )



class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    memory_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    importance: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="medium",
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

    embedding: Mapped[list[float] | None] = mapped_column(
        VECTOR(384),
        nullable=True,
    )