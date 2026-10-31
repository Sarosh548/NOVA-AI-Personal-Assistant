"""add rolling password-reset attempt history

Revision ID: e2f9a6c4b731
Revises: b91c7d3e5f20
Create Date: 2026-10-30 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2f9a6c4b731"
down_revision: Union[str, Sequence[str], None] = "b91c7d3e5f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "password_reset_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_password_reset_attempts_user_attempted_at",
        "password_reset_attempts",
        ["user_id", "attempted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_password_reset_attempts_user_attempted_at",
        table_name="password_reset_attempts",
    )
    op.drop_table("password_reset_attempts")
