"""add password reset challenges

Revision ID: g1b2c3d4e567
Revises: e6a7b8c9d012
Create Date: 2026-10-05 16:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g1b2c3d4e567"
down_revision: Union[str, Sequence[str], None] = "e6a7b8c9d012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "password_reset_challenges",
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
            "code_hash",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "code_salt",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "used_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "sent_at",
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
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_password_reset_challenges_user_id",
        "password_reset_challenges",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        "ix_password_reset_challenges_expires_at",
        "password_reset_challenges",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_password_reset_challenges_expires_at",
        table_name="password_reset_challenges",
    )
    op.drop_index(
        "ix_password_reset_challenges_user_id",
        table_name="password_reset_challenges",
    )
    op.drop_table("password_reset_challenges")
