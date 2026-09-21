"""add reminder processing leases

Revision ID: b8e3c7d1a492
Revises: f7c2a91d4e63
Create Date: 2026-09-21 11:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8e3c7d1a492"
down_revision: Union[str, Sequence[str], None] = "f7c2a91d4e63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add durable reminder processing claim and lease fields."""

    op.add_column(
        "reminders",
        sa.Column(
            "claim_token",
            sa.String(length=64),
            nullable=True,
        ),
    )

    op.add_column(
        "reminders",
        sa.Column(
            "lease_until",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_reminders_status_lease_until",
        "reminders",
        ["status", "lease_until"],
    )


def downgrade() -> None:
    """Remove durable reminder processing claim and lease fields."""

    op.drop_index(
        "ix_reminders_status_lease_until",
        table_name="reminders",
    )

    op.drop_column(
        "reminders",
        "lease_until",
    )

    op.drop_column(
        "reminders",
        "claim_token",
    )
