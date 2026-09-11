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
            # Check for an exact duplicate first
            existing_memory = session.scalar(
                select(Memory).where(
                    Memory.user_id == user_id,
                    Memory.memory_text == memory_text,
                )
            )

            if existing_memory:
                return False

            # Generate embedding once
            embedding = self.embedding_service.create_embedding(
                memory_text
            )

            # Save memory and its embedding
            memory = Memory(
                user_id=user_id,
                memory_text=memory_text,
                category=category,
                importance=importance,
                embedding=embedding.tolist(),
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
        limit: int = 10,
    ) -> list[dict]:
        # Generate the query embedding only once
        query_embedding = (
            self.embedding_service
            .create_embedding(new_memory)
            .tolist()
        )

        # Cosine distance:
        # 0.0 = identical
        # larger value = less similar
        max_distance = 1.0 - threshold

        with Session(engine) as session:
            distance_expression = Memory.embedding.cosine_distance(
                query_embedding
            )

            statement = (
                select(Memory, distance_expression.label("distance"))
                .where(
                    Memory.user_id == user_id,
                    Memory.embedding.is_not(None),
                    distance_expression <= max_distance,
                )
                .order_by(distance_expression)
                .limit(limit)
            )

            results = session.execute(statement).all()

            similar_memories = []

            for memory, distance in results:
                similarity = 1.0 - distance

                similar_memories.append(
                    {
                        "id": memory.id,
                        "memory": memory.memory_text,
                        "similarity": round(similarity, 4),
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

            # Update memory text
            memory.memory_text = memory_text

            # Regenerate embedding because text changed
            embedding = self.embedding_service.create_embedding(
                memory_text
            )

            memory.embedding = embedding.tolist()

            # Update optional fields
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