from sqlalchemy import select
from sqlalchemy.orm import Session

from database.connection import engine
from models.memory import Memory
from services.embedding_service import EmbeddingService


class MemoryService:
    def __init__(self):
        self.embedding_service = EmbeddingService()

    def add_memory(
        self,
        user_id: str,
        memory_text: str,
        category: str,
        importance: str = "medium",
    ) -> bool:
        with Session(engine) as session:
            # Check for an exact duplicate
            existing_memory = session.scalar(
                select(Memory).where(
                    Memory.user_id == user_id,
                    Memory.memory_text == memory_text,
                )
            )

            if existing_memory:
                return False

            memory = Memory(
                user_id=user_id,
                memory_text=memory_text,
                category=category,
                importance=importance,
            )

            session.add(memory)
            session.commit()

            return True

    def get_memories(self, user_id: str) -> list[str]:
        with Session(engine) as session:
            statement = (
                select(Memory)
                .where(Memory.user_id == user_id)
                .order_by(Memory.created_at)
            )

            memories = session.scalars(statement).all()

            return [
                memory.memory_text
                for memory in memories
            ]

    def find_similar_memories(
        self,
        user_id: str,
        new_memory: str,
        threshold: float = 0.85,
    ) -> list[dict]:
        with Session(engine) as session:
            statement = (
                select(Memory)
                .where(Memory.user_id == user_id)
                .order_by(Memory.created_at)
            )

            existing_memories = session.scalars(statement).all()

            similar_memories = []

            for memory in existing_memories:
                score = self.embedding_service.similarity(
                    new_memory,
                    memory.memory_text,
                )

                if score >= threshold:
                    similar_memories.append(
                        {
                            "id": memory.id,
                            "memory": memory.memory_text,
                            "similarity": round(score, 4),
                        }
                    )

            return similar_memories

    def update_memory(
        self,
        memory_id: int,
        memory_text: str,
        category: str | None = None,
        importance: str | None = None,
    ) -> bool:
        with Session(engine) as session:
            memory = session.get(Memory, memory_id)

            if not memory:
                return False

            memory.memory_text = memory_text

            if category is not None:
                memory.category = category

            if importance is not None:
                memory.importance = importance

            session.commit()

            return True

    def delete_memory(self, memory_id: int) -> bool:
        with Session(engine) as session:
            memory = session.get(Memory, memory_id)

            if not memory:
                return False

            session.delete(memory)
            session.commit()

            return True

