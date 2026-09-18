"""add activity events

Revision ID: 7f4a2d91c6b0
Revises: c5b91d7e24a3
Create Date: 2026-09-18 11:15:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7f4a2d91c6b0"
down_revision: Union[str, Sequence[str], None] = (
    "c5b91d7e24a3"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create durable NOVA activity event storage."""

    op.create_table(
        "activity_events",
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
            "workflow_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "event_type",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="info",
        ),
        sa.Column(
            "title",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "id"
        ),
    )

    op.create_index(
        "ix_activity_events_user_id",
        "activity_events",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        "ix_activity_events_conversation_id",
        "activity_events",
        ["conversation_id"],
        unique=False,
    )

    op.create_index(
        "ix_activity_events_workflow_id",
        "activity_events",
        ["workflow_id"],
        unique=False,
    )

    op.create_index(
        "ix_activity_events_user_created",
        "activity_events",
        ["user_id", "created_at"],
        unique=False,
    )

    op.create_index(
        "ix_activity_events_user_type_created",
        "activity_events",
        [
            "user_id",
            "event_type",
            "created_at",
        ],
        unique=False,
    )

    op.create_index(
        "ix_activity_events_workflow_created",
        "activity_events",
        [
            "workflow_id",
            "created_at",
        ],
        unique=False,
    )


def downgrade() -> None:
    """Remove durable NOVA activity event storage."""

    op.drop_index(
        "ix_activity_events_workflow_created",
        table_name="activity_events",
    )

    op.drop_index(
        "ix_activity_events_user_type_created",
        table_name="activity_events",
    )

    op.drop_index(
        "ix_activity_events_user_created",
        table_name="activity_events",
    )

    op.drop_index(
        "ix_activity_events_workflow_id",
        table_name="activity_events",
    )

    op.drop_index(
        "ix_activity_events_conversation_id",
        table_name="activity_events",
    )

    op.drop_index(
        "ix_activity_events_user_id",
        table_name="activity_events",
    )

    op.drop_table(
        "activity_events"
    )