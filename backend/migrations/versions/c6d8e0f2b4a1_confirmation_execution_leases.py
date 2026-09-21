"""add confirmation execution leases

Revision ID: c6d8e0f2b4a1
Revises: a5b7c9d1e3f0
Create Date: 2026-09-21 10:16:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c6d8e0f2b4a1"
down_revision: Union[str, Sequence[str], None] = (
    "d4e8b1c6a2f9"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add durable confirmation execution claim state."""

    op.add_column(
        "confirmations",
        sa.Column(
            "claim_token",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        "confirmations",
        sa.Column(
            "lease_until",
            sa.DateTime(),
            nullable=True,
        ),
    )
    op.add_column(
        "confirmations",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.create_index(
        "ix_confirmations_lease_until",
        "confirmations",
        ["lease_until"],
        unique=False,
    )


def downgrade() -> None:
    """Remove durable confirmation execution claim state."""

    op.drop_index(
        "ix_confirmations_lease_until",
        table_name="confirmations",
    )

    op.drop_column(
        "confirmations",
        "attempt_count",
    )
    op.drop_column(
        "confirmations",
        "lease_until",
    )
    op.drop_column(
        "confirmations",
        "claim_token",
    )
