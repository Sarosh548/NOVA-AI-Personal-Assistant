from sqlalchemy import select, text
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

            # Save memory and embedding
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
        # Validate search parameters
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0.0 and 1.0")

        if limit < 1:
            raise ValueError("limit must be greater than 0")

        # Generate the query embedding only once
        query_embedding = (
            self.embedding_service
            .create_embedding(new_memory)
            .tolist()
        )

        with Session(engine) as session:
            # Enable iterative HNSW scans for filtered vector search.
            # This is useful when user_id filtering reduces the number
            # of candidate vectors returned by the approximate index.
            session.execute(
                text("SET LOCAL hnsw.iterative_scan = strict_order")
            )

            distance_expression = Memory.embedding.cosine_distance(
                query_embedding
            )

            statement = (
                select(
                    Memory,
                    distance_expression.label("distance"),
                )
                .where(
                    Memory.user_id == user_id,
                    Memory.embedding.is_not(None),
                )
                .order_by(distance_expression)
                .limit(limit)
            )

            results = session.execute(statement).all()

            similar_memories = []

            for memory, distance in results:
                distance = float(distance)
                similarity = 1.0 - distance

                # Apply semantic similarity threshold
                if similarity < threshold:
                    continue

                similar_memories.append(
                    {
                        "id": memory.id,
                        "memory": memory.memory_text,
                        "similarity": round(
                            similarity,
                            4,
                        ),
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