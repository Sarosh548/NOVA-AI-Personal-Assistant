"""add durable realtime voice session leases

Revision ID: f8d3c1a7e5b2
Revises: f7c2a91d4e63
Create Date: 2026-09-23 06:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8d3c1a7e5b2"
down_revision: Union[str, Sequence[str], None] = "f1a6c9d3e7b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create durable realtime voice session ownership leases."""

    op.create_table(
        "voice_session_leases",
        sa.Column(
            "id",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "lease_until",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(),
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
            name="uq_voice_session_leases_user",
        ),
    )

    op.create_index(
        "ix_voice_session_leases_lease_until",
        "voice_session_leases",
        ["lease_until"],
        unique=False,
    )


def downgrade() -> None:
    """Remove durable realtime voice session ownership leases."""

    op.drop_index(
        "ix_voice_session_leases_lease_until",
        table_name="voice_session_leases",
    )

    op.drop_table(
        "voice_session_leases"
    )
