from sqlalchemy import select
from sqlalchemy.orm import Session

from database.connection import engine
from models.memory import Memory


class MemoryService:
    def add_memory(
        self,
        user_id: str,
        memory_text: str,
        category: str,
        importance: str = "medium",
    ) -> None:
        with Session(engine) as session:
            memory = Memory(
                user_id=user_id,
                memory_text=memory_text,
                category=category,
                importance=importance,
            )

            session.add(memory)
            session.commit()

    def get_memories(self, user_id: str) -> list[str]:
        with Session(engine) as session:
            statement = (
                select(Memory)
                .where(Memory.user_id == user_id)
                .order_by(Memory.created_at)
            )

            memories = session.scalars(statement).all()

            return [memory.memory_text for memory in memories]