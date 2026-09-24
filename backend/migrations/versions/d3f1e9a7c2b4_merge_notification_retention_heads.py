"""merge notification delivery retention with existing migration heads

Revision ID: d3f1e9a7c2b4
Revises: f7c2a91d4e63, c9e2a5b7d1f4
Create Date: 2026-09-24 12:40:00.000000

"""

from typing import Sequence, Union


revision: str = "d3f1e9a7c2b4"
down_revision: Union[str, Sequence[str], None] = (
    "f7c2a91d4e63",
    "c9e2a5b7d1f4",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge the existing migration heads after retention cleanup."""
    pass


def downgrade() -> None:
    """Leave the merged migration graph intact on downgrade."""
    pass
