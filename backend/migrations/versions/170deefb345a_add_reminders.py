"""add reminders

Revision ID: 170deefb345a
Revises: 9d949e6b3445
Create Date: 2026-09-13 21:09:58.828708

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "170deefb345a"
down_revision: Union[str, Sequence[str], None] = "9d949e6b3445"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the reminders table."""

    op.create_table(
        "reminders",
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
            "reminder_time",
            sa.DateTime(),
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
            "updated_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Remove the reminders table."""

    op.drop_table("reminders")