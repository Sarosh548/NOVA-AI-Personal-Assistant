"""add workflow worker leases

Revision ID: b6c9d2e4f781
Revises: 14fa9c3ca24b
Create Date: 2026-09-20 16:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b6c9d2e4f781"
down_revision: Union[str, Sequence[str], None] = "14fa9c3ca24b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add durable worker lease state to workflows."""

    op.add_column(
        "workflows",
        sa.Column(
            "claim_token",
            sa.String(length=64),
            nullable=True,
        ),
    )

    op.add_column(
        "workflows",
        sa.Column(
            "lease_until",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.add_column(
        "workflows",
        sa.Column(
            "heartbeat_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_workflows_lease_recovery",
        "workflows",
        [
            "execution_mode",
            "status",
            "lease_until",
        ],
        unique=False,
    )


def downgrade() -> None:
    """Remove durable worker lease state from workflows."""

    op.drop_index(
        "ix_workflows_lease_recovery",
        table_name="workflows",
    )

    op.drop_column(
        "workflows",
        "heartbeat_at",
    )

    op.drop_column(
        "workflows",
        "lease_until",
    )

    op.drop_column(
        "workflows",
        "claim_token",
    )