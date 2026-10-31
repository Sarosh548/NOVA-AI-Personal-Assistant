"""add bounded retry scheduling to reminders

Revision ID: b91c7d3e5f20
Revises: a6e2c9b7d410
Create Date: 2026-10-30 17:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b91c7d3e5f20"
down_revision: Union[str, Sequence[str], None] = "a6e2c9b7d410"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reminders",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "reminders",
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_reminders_status_next_attempt_at",
        "reminders",
        ["status", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reminders_status_next_attempt_at",
        table_name="reminders",
    )
    op.drop_column("reminders", "next_attempt_at")
    op.drop_column("reminders", "attempt_count")
