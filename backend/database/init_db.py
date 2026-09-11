from database.base import Base
from database.connection import engine

from models.memory import Memory
from models.message import Message
from models.conversation import Conversation


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    print("NOVA database tables created successfully!")


if __name__ == "__main__":
    initialize_database()