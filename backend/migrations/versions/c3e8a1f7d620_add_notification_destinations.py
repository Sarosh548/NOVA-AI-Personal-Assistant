"""add notification destinations

Revision ID: c3e8a1f7d620
Revises: b6c9d2e4f781
Create Date: 2026-09-20 17:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3e8a1f7d620"
down_revision: Union[str, Sequence[str], None] = "b6c9d2e4f781"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create durable user notification destinations."""

    op.create_table(
        "notification_destinations",
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
            "channel",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "destination",
            sa.String(length=500),
            nullable=False,
        ),
        sa.Column(
            "label",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id"
        ),
        sa.UniqueConstraint(
            "user_id",
            "channel",
            "destination",
            name=(
                "uq_notification_destinations_user_channel_destination"
            ),
        ),
    )

    op.create_index(
        "ix_notification_destinations_user_channel",
        "notification_destinations",
        [
            "user_id",
            "channel",
        ],
        unique=False,
    )

    op.create_index(
        "ix_notification_destinations_user_enabled",
        "notification_destinations",
        [
            "user_id",
            "is_enabled",
        ],
        unique=False,
    )

    op.create_index(
        "ix_notification_destinations_user_channel_default",
        "notification_destinations",
        [
            "user_id",
            "channel",
            "is_default",
        ],
        unique=False,
    )


def downgrade() -> None:
    """Remove durable user notification destinations."""

    op.drop_index(
        "ix_notification_destinations_user_channel_default",
        table_name="notification_destinations",
    )

    op.drop_index(
        "ix_notification_destinations_user_enabled",
        table_name="notification_destinations",
    )

    op.drop_index(
        "ix_notification_destinations_user_channel",
        table_name="notification_destinations",
    )

    op.drop_table(
        "notification_destinations"
    )