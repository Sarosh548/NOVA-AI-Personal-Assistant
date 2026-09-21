from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text
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



class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
    )

    source: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    content_hash: Mapped[str] = mapped_column(
        String(64),
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
        Index(
            "ix_knowledge_documents_user_id",
            "user_id",
        ),
        Index(
            "ix_knowledge_documents_user_hash",
            "user_id",
            "content_hash",
            unique=True,
        ),
    )
