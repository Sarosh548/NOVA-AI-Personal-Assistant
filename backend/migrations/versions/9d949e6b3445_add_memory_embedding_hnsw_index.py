"""add memory embedding hnsw index

Revision ID: 9d949e6b3445
Revises: 505cad70e18a
Create Date: 2026-09-11 20:57:06.077810

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "9d949e6b3445"
down_revision: Union[str, Sequence[str], None] = "505cad70e18a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create an HNSW index for cosine similarity search."""
    op.execute(
        """
        CREATE INDEX ix_memories_embedding_hnsw
        ON memories
        USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL;
        """
    )


def downgrade() -> None:
    """Drop the HNSW index."""
    op.execute(
        """
        DROP INDEX IF EXISTS ix_memories_embedding_hnsw;
        """
    )