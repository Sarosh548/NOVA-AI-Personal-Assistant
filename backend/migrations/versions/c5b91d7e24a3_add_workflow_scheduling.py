"""add workflow scheduling

Revision ID: c5b91d7e24a3
Revises: c1a7d8e90f12
Create Date: 2026-09-17 20:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c5b91d7e24a3"
down_revision: Union[str, Sequence[str], None] = (
    "c1a7d8e90f12"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add autonomous workflow scheduling support."""

    op.add_column(
        "workflows",
        sa.Column(
            "scheduled_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_workflows_scheduled_at",
        "workflows",
        ["scheduled_at"],
        unique=False,
    )

    op.create_index(
        "ix_workflows_autonomous_due",
        "workflows",
        [
            "execution_mode",
            "status",
            "scheduled_at",
        ],
        unique=False,
    )


def downgrade() -> None:
    """Remove autonomous workflow scheduling support."""

    op.drop_index(
        "ix_workflows_autonomous_due",
        table_name="workflows",
    )

    op.drop_index(
        "ix_workflows_scheduled_at",
        table_name="workflows",
    )

    op.drop_column(
        "workflows",
        "scheduled_at",
    )