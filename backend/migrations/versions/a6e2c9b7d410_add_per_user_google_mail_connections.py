"""add encrypted per-user Google Mail connections

Revision ID: a6e2c9b7d410
Revises: d3f1e9a7c2b4
Create Date: 2026-10-09 16:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a6e2c9b7d410"
down_revision: Union[str, Sequence[str], None] = "g1b2c3d4e567"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_connections",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("email_address", sa.String(length=255), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("token_refresh_claim_token", sa.String(length=100), nullable=True),
        sa.Column("token_refresh_lease_until", sa.DateTime(), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "provider", name="uq_email_connections_user_provider"),
    )
    op.create_index("ix_email_connections_user_id", "email_connections", ["user_id"], unique=False)
    op.create_index("ix_email_connections_token_expires_at", "email_connections", ["token_expires_at"], unique=False)
    op.create_index("ix_email_connections_token_refresh_lease_until", "email_connections", ["token_refresh_lease_until"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_email_connections_token_refresh_lease_until", table_name="email_connections")
    op.drop_index("ix_email_connections_token_expires_at", table_name="email_connections")
    op.drop_index("ix_email_connections_user_id", table_name="email_connections")
    op.drop_table("email_connections")
