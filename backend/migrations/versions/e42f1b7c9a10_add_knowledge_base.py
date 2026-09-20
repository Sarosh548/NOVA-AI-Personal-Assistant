"""add knowledge base documents and chunks

Revision ID: e42f1b7c9a10
Revises: 2816b8835a35
Create Date: 2026-09-20 19:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR


revision: str = "e42f1b7c9a10"
down_revision: Union[str, Sequence[str], None] = (
    "2816b8835a35"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create durable knowledge documents and semantic chunks."""

    op.create_table(
        "knowledge_documents",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "title",
            sa.String(length=300),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=1000),
            nullable=True,
        ),
        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_knowledge_documents_user_id",
        "knowledge_documents",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        "ix_knowledge_documents_user_hash",
        "knowledge_documents",
        ["user_id", "content_hash"],
        unique=True,
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "chunk_index",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "embedding",
            VECTOR(384),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_knowledge_chunks_document_index",
        ),
    )

    op.create_index(
        "ix_knowledge_chunks_document_id",
        "knowledge_chunks",
        ["document_id"],
        unique=False,
    )

    op.create_index(
        "ix_knowledge_chunks_user_id",
        "knowledge_chunks",
        ["user_id"],
        unique=False,
    )

    op.execute(
        """
        CREATE INDEX ix_knowledge_chunks_embedding_hnsw
        ON knowledge_chunks
        USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL;
        """
    )


def downgrade() -> None:
    """Remove knowledge chunks and documents."""

    op.execute(
        """
        DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_hnsw;
        """
    )

    op.drop_index(
        "ix_knowledge_chunks_user_id",
        table_name="knowledge_chunks",
    )

    op.drop_index(
        "ix_knowledge_chunks_document_id",
        table_name="knowledge_chunks",
    )

    op.drop_table(
        "knowledge_chunks"
    )

    op.drop_index(
        "ix_knowledge_documents_user_hash",
        table_name="knowledge_documents",
    )

    op.drop_index(
        "ix_knowledge_documents_user_id",
        table_name="knowledge_documents",
    )

    op.drop_table(
        "knowledge_documents"
    )
