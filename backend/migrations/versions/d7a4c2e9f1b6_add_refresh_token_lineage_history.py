"""add refresh token lineage history

Revision ID: d7a4c2e9f1b6
Revises: c6d8e0f2b4a1
Create Date: 2026-09-21 14:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7a4c2e9f1b6"
down_revision: Union[str, Sequence[str], None] = (
    "c6d8e0f2b4a1"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add durable refresh-token lineage history."""
    op.create_table(
        "refresh_token_history",
        sa.Column(
            "id",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "token_hash",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "replaced_by_token_hash",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "replaced_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "token_hash",
            name="uq_refresh_token_history_token_hash",
        ),
    )

    op.create_index(
        "ix_refresh_token_history_session_id",
        "refresh_token_history",
        ["session_id"],
        unique=False,
    )

    op.create_index(
        "ix_refresh_token_history_replaced_at",
        "refresh_token_history",
        ["replaced_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove durable refresh-token lineage history."""
    op.drop_index(
        "ix_refresh_token_history_replaced_at",
        table_name="refresh_token_history",
    )
    op.drop_index(
        "ix_refresh_token_history_session_id",
        table_name="refresh_token_history",
    )
    op.drop_table("refresh_token_history")
