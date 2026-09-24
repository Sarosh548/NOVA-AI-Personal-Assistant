"""add notification delivery retention index

Revision ID: c9e2a5b7d1f4
Revises: f8d3c1a7e5b2
Create Date: 2026-09-24 12:35:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "c9e2a5b7d1f4"
down_revision: Union[str, Sequence[str], None] = (
    "f8d3c1a7e5b2"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add an index for terminal notification retention cleanup."""
    op.create_index(
        "ix_notification_deliveries_status_updated",
        "notification_deliveries",
        ["status", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the notification delivery retention index."""
    op.drop_index(
        "ix_notification_deliveries_status_updated",
        table_name="notification_deliveries",
    )
