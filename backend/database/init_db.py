from database.base import Base
from database.connection import engine

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


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    print("NOVA database tables created successfully!")


if __name__ == "__main__":
    initialize_database()