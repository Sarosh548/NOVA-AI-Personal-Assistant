"""add email verification

Revision ID: e6a7b8c9d012
Revises: d3f1e9a7c2b4
Create Date: 2026-10-05 16:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6a7b8c9d012"
down_revision: Union[str, Sequence[str], None] = "d3f1e9a7c2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "email_verified_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.create_table(
        "email_verification_challenges",
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
        "ix_email_verification_challenges_user_id",
        "email_verification_challenges",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        "ix_email_verification_challenges_expires_at",
        "email_verification_challenges",
        ["expires_at"],
        unique=False,
    )

    op.execute(
        """
        UPDATE users
        SET email_verified_at = created_at
        WHERE id IN (
            SELECT ai.user_id
            FROM auth_identities ai
            WHERE ai.provider = 'password'
              AND ai.provider_subject LIKE '%@%'
        )
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_verification_challenges_expires_at",
        table_name="email_verification_challenges",
    )
    op.drop_index(
        "ix_email_verification_challenges_user_id",
        table_name="email_verification_challenges",
    )
    op.drop_table("email_verification_challenges")
    op.drop_column("users", "email_verified_at")
