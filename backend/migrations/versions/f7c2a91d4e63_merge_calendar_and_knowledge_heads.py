"""merge calendar and knowledge base migration heads

Revision ID: f7c2a91d4e63
Revises: 8a14c6f2b931, e42f1b7c9a10
Create Date: 2026-09-20 19:17:00.000000

"""

from typing import Sequence, Union


revision: str = "f7c2a91d4e63"
down_revision: Union[str, Sequence[str], None] = (
    "8a14c6f2b931",
    "e42f1b7c9a10",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge the existing Calendar and Knowledge migration heads."""
    pass


def downgrade() -> None:
    """Recreate the two independent migration heads."""
    pass
