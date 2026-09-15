"""add tasks

Revision ID: 247d7e638df6
Revises: 170deefb345a
Create Date: 2026-09-15 09:17:11.401707

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "247d7e638df6"
down_revision: Union[str, Sequence[str], None] = "170deefb345a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the tasks table."""

    op.create_table(
        "tasks",
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
            "title",
            sa.String(length=300),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.String(length=10),
            nullable=False,
        ),
        sa.Column(
            "due_at",
            sa.DateTime(),
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
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_tasks_user_id",
        "tasks",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        "ix_tasks_user_status_due",
        "tasks",
        ["user_id", "status", "due_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the tasks table."""

    op.drop_index(
        "ix_tasks_user_status_due",
        table_name="tasks",
    )

    op.drop_index(
        "ix_tasks_user_id",
        table_name="tasks",
    )

    op.drop_table("tasks")
