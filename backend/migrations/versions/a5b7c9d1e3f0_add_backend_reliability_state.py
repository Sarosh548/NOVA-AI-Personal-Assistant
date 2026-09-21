"""add backend reliability state

Revision ID: a5b7c9d1e3f0
Revises: b8e3c7d1a492
Create Date: 2026-09-21 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a5b7c9d1e3f0"
down_revision: Union[str, Sequence[str], None] = (
    "b8e3c7d1a492"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create durable reliability and audit state."""

    op.create_table(
        "audit_events",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "event_type",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "action",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
        ),
        sa.Column(
            "resource_type",
            sa.String(length=50),
            nullable=True,
        ),
        sa.Column(
            "resource_id",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "request_id",
            sa.String(length=128),
            nullable=True,
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_audit_events_user_id",
        "audit_events",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_request_id",
        "audit_events",
        ["request_id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_user_created",
        "audit_events",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_type_created",
        "audit_events",
        ["event_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_request_created",
        "audit_events",
        ["request_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "notification_deliveries",
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
            "channel",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "idempotency_key",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="processing",
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "claim_token",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "lease_until",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "sent_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "last_attempt_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "last_error",
            sa.Text(),
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
        sa.UniqueConstraint(
            "user_id",
            "channel",
            "idempotency_key",
            name="uq_notification_delivery_key",
        ),
    )

    op.create_index(
        "ix_notification_deliveries_status_lease",
        "notification_deliveries",
        ["status", "lease_until"],
        unique=False,
    )
    op.create_index(
        "ix_notification_deliveries_user_created",
        "notification_deliveries",
        ["user_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "idempotency_records",
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
            "endpoint",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "idempotency_key",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "request_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="processing",
        ),
        sa.Column(
            "response_status",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "response_body",
            sa.JSON(),
            nullable=True,
        ),
        sa.Column(
            "claim_token",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "lease_until",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "last_error",
            sa.Text(),
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
        sa.UniqueConstraint(
            "user_id",
            "endpoint",
            "idempotency_key",
            name="uq_idempotency_request_key",
        ),
    )

    op.create_index(
        "ix_idempotency_status_lease",
        "idempotency_records",
        ["status", "lease_until"],
        unique=False,
    )
    op.create_index(
        "ix_idempotency_expires",
        "idempotency_records",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_idempotency_user_created",
        "idempotency_records",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove durable reliability and audit state."""

    op.drop_index(
        "ix_idempotency_user_created",
        table_name="idempotency_records",
    )
    op.drop_index(
        "ix_idempotency_expires",
        table_name="idempotency_records",
    )
    op.drop_index(
        "ix_idempotency_status_lease",
        table_name="idempotency_records",
    )
    op.drop_table(
        "idempotency_records"
    )

    op.drop_index(
        "ix_notification_deliveries_user_created",
        table_name="notification_deliveries",
    )
    op.drop_index(
        "ix_notification_deliveries_status_lease",
        table_name="notification_deliveries",
    )
    op.drop_table(
        "notification_deliveries"
    )

    op.drop_index(
        "ix_audit_events_request_created",
        table_name="audit_events",
    )
    op.drop_index(
        "ix_audit_events_type_created",
        table_name="audit_events",
    )
    op.drop_index(
        "ix_audit_events_user_created",
        table_name="audit_events",
    )
    op.drop_index(
        "ix_audit_events_request_id",
        table_name="audit_events",
    )
    op.drop_index(
        "ix_audit_events_user_id",
        table_name="audit_events",
    )
    op.drop_table(
        "audit_events"
    )
