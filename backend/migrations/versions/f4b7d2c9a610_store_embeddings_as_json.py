"""store embeddings as portable JSON

Revision ID: f4b7d2c9a610
Revises: e3a6d9f2b417
Create Date: 2026-11-22 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "f4b7d2c9a610"
down_revision: Union[str, Sequence[str], None] = "e3a6d9f2b417"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Convert legacy pgvector columns to JSON without losing vector values."""
    op.execute("DROP INDEX IF EXISTS ix_memories_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_hnsw")

    op.execute(
        """
        ALTER TABLE memories
        ALTER COLUMN embedding TYPE JSON
        USING embedding::text::json
        """
    )
    op.execute(
        """
        ALTER TABLE knowledge_chunks
        ALTER COLUMN embedding TYPE JSON
        USING embedding::text::json
        """
    )


def downgrade() -> None:
    """Refuse a downgrade that would silently break JSON-backed embeddings."""
    raise RuntimeError(
        "Embedding storage migration is intentionally irreversible. "
        "Restoring VECTOR columns requires the pgvector server extension."
    )
