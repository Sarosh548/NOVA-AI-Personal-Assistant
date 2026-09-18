"""add activity digest deliveries

Revision ID: d18f6a9c42e1
Revises: 7f4a2d91c6b0
Create Date: 2026-09-18 13:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d18f6a9c42e1"
down_revision: Union[str, Sequence[str], None] = (
    "7f4a2d91c6b0"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create durable proactive activity digest delivery state."""

    op.create_table(
        "activity_digest_deliveries",
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
            "digest_date",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "digest_type",
            sa.String(length=50),
            nullable=False,
            server_default="daily_activity",
        ),
        sa.Column(
            "delivery_key",
            sa.String(length=300),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="processing",
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "claim_token",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "lease_until",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "last_attempt_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "sent_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "last_error",
            sa.Text(),
            nullable=True,
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
            "digest_date",
            "digest_type",
            name=(
                "uq_activity_digest_delivery_slot"
            ),
        ),
        sa.UniqueConstraint(
            "delivery_key"
        ),
    )

    op.create_index(
        "ix_activity_digest_deliveries_user_date",
        "activity_digest_deliveries",
        [
            "user_id",
            "digest_date",
        ],
        unique=False,
    )

    op.create_index(
        "ix_activity_digest_deliveries_status_lease",
        "activity_digest_deliveries",
        [
            "status",
            "lease_until",
        ],
        unique=False,
    )


def downgrade() -> None:
    """Remove proactive activity digest delivery state."""

    op.drop_index(
        "ix_activity_digest_deliveries_status_lease",
        table_name="activity_digest_deliveries",
    )

    op.drop_index(
        "ix_activity_digest_deliveries_user_date",
        table_name="activity_digest_deliveries",
    )

    op.drop_table(
        "activity_digest_deliveries"
    )