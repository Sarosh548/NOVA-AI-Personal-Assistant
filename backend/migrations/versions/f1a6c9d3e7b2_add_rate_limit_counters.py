"""add durable API rate limit counters

Revision ID: f1a6c9d3e7b2
Revises: b8e3c7d1a492, d7a4c2e9f1b6
Create Date: 2026-09-21 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a6c9d3e7b2"
down_revision: Union[str, Sequence[str], None] = (
    "b8e3c7d1a492",
    "d7a4c2e9f1b6",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create durable API rate limit counters."""
    op.create_table(
        "rate_limit_counters",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "principal_key",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "scope",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "window_start",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "request_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "principal_key",
            "scope",
            name="uq_rate_limit_principal_scope",
        ),
    )

    op.create_index(
        "ix_rate_limit_scope_window",
        "rate_limit_counters",
        ["scope", "window_start"],
        unique=False,
    )


def downgrade() -> None:
    """Remove durable API rate limit counters."""
    op.drop_index(
        "ix_rate_limit_scope_window",
        table_name="rate_limit_counters",
    )

    op.drop_table(
        "rate_limit_counters"
    )
