"""add memory embeddings

Revision ID: 505cad70e18a
Revises: 093526b34f89
Create Date: 2026-09-11 18:34:48.634516

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR


# revision identifiers, used by Alembic.
revision: str = "505cad70e18a"
down_revision: Union[str, Sequence[str], None] = "093526b34f89"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "memories",
        sa.Column(
            "embedding",
            VECTOR(384),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("memories", "embedding")