"""add idempotent refresh rotation request hash

Revision ID: e3a6d9f2b417
Revises: e2f9a6c4b731
Create Date: 2026-10-30 18:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3a6d9f2b417"
down_revision: Union[str, Sequence[str], None] = "e2f9a6c4b731"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "refresh_token_history",
        sa.Column("rotation_request_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("refresh_token_history", "rotation_request_hash")
