"""add durable workflow runtime

Revision ID: c1a7d8e90f12
Revises: 247d7e638df6
Create Date: 2026-09-17 20:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1a7d8e90f12"
down_revision: Union[str, Sequence[str], None] = (
    "247d7e638df6"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create durable workflow runtime tables."""

    op.create_table(
        "workflows",
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
            "status",
            sa.String(length=30),
            nullable=False,
        ),
        sa.Column(
            "execution_mode",
            sa.String(length=30),
            nullable=False,
        ),
        sa.Column(
            "plan",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "result",
            sa.JSON(),
            nullable=True,
        ),
        sa.Column(
            "error",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "idempotency_key",
            sa.String(length=200),
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
        sa.Column(
            "started_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint(
            "id"
        ),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_workflows_user_idempotency",
        ),
    )

    op.create_index(
        "ix_workflows_user_id",
        "workflows",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        "ix_workflows_conversation_id",
        "workflows",
        ["conversation_id"],
        unique=False,
    )

    op.create_index(
        "ix_workflows_status",
        "workflows",
        ["status"],
        unique=False,
    )

    op.create_index(
        "ix_workflows_user_status_created",
        "workflows",
        [
            "user_id",
            "status",
            "created_at",
        ],
        unique=False,
    )

    op.create_table(
        "workflow_steps",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "workflow_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "step_id",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "position",
            sa.Integer(),
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
            "data",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "depends_on",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
        ),
        sa.Column(
            "result",
            sa.JSON(),
            nullable=True,
        ),
        sa.Column(
            "error",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "attempts",
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
        sa.Column(
            "started_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id"
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "step_id",
            name="uq_workflow_steps_workflow_step",
        ),
    )

    op.create_index(
        "ix_workflow_steps_workflow_id",
        "workflow_steps",
        ["workflow_id"],
        unique=False,
    )

    op.create_index(
        "ix_workflow_steps_status",
        "workflow_steps",
        ["status"],
        unique=False,
    )

    op.create_index(
        "ix_workflow_steps_workflow_status",
        "workflow_steps",
        [
            "workflow_id",
            "status",
        ],
        unique=False,
    )


def downgrade() -> None:
    """Remove durable workflow runtime tables."""

    op.drop_index(
        "ix_workflow_steps_workflow_status",
        table_name="workflow_steps",
    )

    op.drop_index(
        "ix_workflow_steps_status",
        table_name="workflow_steps",
    )

    op.drop_index(
        "ix_workflow_steps_workflow_id",
        table_name="workflow_steps",
    )

    op.drop_table(
        "workflow_steps"
    )

    op.drop_index(
        "ix_workflows_user_status_created",
        table_name="workflows",
    )

    op.drop_index(
        "ix_workflows_status",
        table_name="workflows",
    )

    op.drop_index(
        "ix_workflows_conversation_id",
        table_name="workflows",
    )

    op.drop_index(
        "ix_workflows_user_id",
        table_name="workflows",
    )

    op.drop_table(
        "workflows"
    )