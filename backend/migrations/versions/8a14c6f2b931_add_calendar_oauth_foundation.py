"""add calendar oauth foundation

Revision ID: 8a14c6f2b931
Revises: c3e8a1f7d620
Create Date: 2026-09-20 19:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8a14c6f2b931"
down_revision: Union[str, Sequence[str], None] = "c3e8a1f7d620"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create durable Google Calendar OAuth state and connections."""

    op.create_table(
        "calendar_connections",
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
            "provider",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "calendar_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "encrypted_access_token",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "encrypted_refresh_token",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "token_expires_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "scopes",
            sa.Text(),
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
            "provider",
            name="uq_calendar_connections_user_provider",
        ),
    )

    op.create_index(
        "ix_calendar_connections_user_id",
        "calendar_connections",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        "ix_calendar_connections_token_expires_at",
        "calendar_connections",
        ["token_expires_at"],
        unique=False,
    )

    op.create_table(
        "oauth_states",
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
            "provider",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "state_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "used_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
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
            "state_hash",
            name="uq_oauth_states_state_hash",
        ),
    )

    op.create_index(
        "ix_oauth_states_user_provider",
        "oauth_states",
        ["user_id", "provider"],
        unique=False,
    )

    op.create_index(
        "ix_oauth_states_expires_at",
        "oauth_states",
        ["expires_at"],
        unique=False,
    )

    op.create_index(
        "ix_oauth_states_used_at",
        "oauth_states",
        ["used_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove calendar OAuth state and connections."""

    op.drop_index(
        "ix_oauth_states_used_at",
        table_name="oauth_states",
    )

    op.drop_index(
        "ix_oauth_states_expires_at",
        table_name="oauth_states",
    )

    op.drop_index(
        "ix_oauth_states_user_provider",
        table_name="oauth_states",
    )

    op.drop_table(
        "oauth_states"
    )

    op.drop_index(
        "ix_calendar_connections_token_expires_at",
        table_name="calendar_connections",
    )

    op.drop_index(
        "ix_calendar_connections_user_id",
        table_name="calendar_connections",
    )

    op.drop_table(
        "calendar_connections"
    )
