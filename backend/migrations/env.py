from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

from database.connection import database_url
from database.base import Base

from models.memory import Memory
from models.message import Message
from models.conversation import Conversation
from models.reminder import Reminder
from models.task import Task
from models.permission import Permission
from models.confirmation import Confirmation
from models.workflow import Workflow
from models.workflow_step import WorkflowStep
from models.activity_event import ActivityEvent
from models.activity_digest_delivery import (
    ActivityDigestDelivery,
)
from models.user import User
from models.user_notification_preferences import (
    UserNotificationPreferences,
)
from models.auth_identity import AuthIdentity
from models.user_session import UserSession

# Alembic Config object
config = context.config


# Logging configuration
if config.config_file_name is not None:
    fileConfig(
        config.config_file_name
    )


# SQLAlchemy metadata for autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""

    url = database_url

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={
            "paramstyle": "named"
        },
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode."""

    configuration = config.get_section(
        config.config_ini_section
    )

    configuration["sqlalchemy.url"] = database_url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
