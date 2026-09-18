"""add user notification preferences

Revision ID: 2816b8835a35
Revises: d18f6a9c42e1
Create Date: 2026-09-18 15:54:12.010737

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2816b8835a35"
down_revision: Union[str, Sequence[str], None] = (
    "d18f6a9c42e1"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create durable user notification preferences."""

    op.create_table(
        "user_notification_preferences",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "timezone",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "daily_activity_digest_enabled",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "delivery_hour",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "delivery_minute",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "id"
        ),
        sa.UniqueConstraint(
            "user_id",
            name="uq_user_notification_preferences_user",
        ),
    )


def downgrade() -> None:
    """Remove durable user notification preferences."""

    op.drop_table(
        "user_notification_preferences"
    )