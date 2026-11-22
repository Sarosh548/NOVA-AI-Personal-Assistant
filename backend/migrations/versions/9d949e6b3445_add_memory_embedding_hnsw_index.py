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
    """No database vector index is needed for Python cosine search."""
    pass


def downgrade() -> None:
    """The upgrade does not create any database objects."""
    pass
