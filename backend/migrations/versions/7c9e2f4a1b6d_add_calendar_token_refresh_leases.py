"""add Calendar token refresh leases

Revision ID: 7c9e2f4a1b6d
Revises: f8d3c1a7e5b2
Create Date: 2026-09-24 13:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c9e2f4a1b6d"
down_revision: Union[str, Sequence[str], None] = "f8d3c1a7e5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add durable fields for Calendar token refresh ownership."""

    op.add_column(
        "calendar_connections",
        sa.Column(
            "token_refresh_claim_token",
            sa.String(length=100),
            nullable=True,
        ),
    )

    op.add_column(
        "calendar_connections",
        sa.Column(
            "token_refresh_lease_until",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_calendar_connections_token_refresh_lease_until",
        "calendar_connections",
        ["token_refresh_lease_until"],
        unique=False,
    )


def downgrade() -> None:
    """Remove durable Calendar token refresh ownership fields."""

    op.drop_index(
        "ix_calendar_connections_token_refresh_lease_until",
        table_name="calendar_connections",
    )

    op.drop_column(
        "calendar_connections",
        "token_refresh_lease_until",
    )

    op.drop_column(
        "calendar_connections",
        "token_refresh_claim_token",
    )
