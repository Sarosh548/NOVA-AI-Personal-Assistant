"""create confirmation and permission tables

Revision ID: d4e8b1c6a2f9
Revises: a5b7c9d1e3f0
Create Date: 2026-09-21 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e8b1c6a2f9"
down_revision: Union[str, Sequence[str], None] = (
    "a5b7c9d1e3f0"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create durable permission and confirmation tables."""

    op.create_table(
        "permissions",
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
            "tool",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "action",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "mode",
            sa.String(length=20),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "tool",
            "action",
            name="uq_permission_user_tool_action",
        ),
    )

    op.create_index(
        "ix_permissions_user_id",
        "permissions",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        "ix_permissions_tool",
        "permissions",
        ["tool"],
        unique=False,
    )

    op.create_table(
        "confirmations",
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
            "conversation_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "tool",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "action",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "data",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_confirmations_user_id",
        "confirmations",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        "ix_confirmations_conversation_id",
        "confirmations",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove durable permission and confirmation tables."""

    op.drop_index(
        "ix_confirmations_conversation_id",
        table_name="confirmations",
    )

    op.drop_index(
        "ix_confirmations_user_id",
        table_name="confirmations",
    )

    op.drop_table("confirmations")

    op.drop_index(
        "ix_permissions_tool",
        table_name="permissions",
    )

    op.drop_index(
        "ix_permissions_user_id",
        table_name="permissions",
    )

    op.drop_table("permissions")
