"""add conversations and conversation_id

Revision ID: 093526b34f89
Revises:
Create Date: 2026-09-11 09:32:20.045400

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "093526b34f89"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # 1. Create conversations table
    op.create_table(
        "conversations",
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
            sa.String(length=200),
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

    # 2. Add conversation_id temporarily as nullable
    op.add_column(
        "messages",
        sa.Column(
            "conversation_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    # 3. Create one conversation for each existing user
    op.execute(
        sa.text(
            """
            INSERT INTO conversations
                (user_id, title, created_at, updated_at)
            SELECT DISTINCT
                user_id,
                'Imported Conversation',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM messages
            """
        )
    )

    # 4. Attach existing messages to their user's conversation
    op.execute(
        sa.text(
            """
            UPDATE messages
            SET conversation_id = conversations.id
            FROM conversations
            WHERE messages.user_id = conversations.user_id
            """
        )
    )

    # 5. Make conversation_id required
    op.alter_column(
        "messages",
        "conversation_id",
        existing_type=sa.Integer(),
        nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_column("messages", "conversation_id")
    op.drop_table("conversations")