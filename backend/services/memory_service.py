from sqlalchemy import select, text
from sqlalchemy.orm import Session

from database.connection import engine
from models.memory import Memory
from services.embedding_service import EmbeddingService


class MemoryService:
    def __init__(self):
        self.embedding_service = EmbeddingService()

    def _find_similar_by_embedding(
        self,
        session: Session,
        user_id: str,
        query_embedding: list[float],
        threshold: float,
        limit: int = 10,
    ) -> list[dict]:
        """Find memories similar to an already-generated embedding."""

        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0.0 and 1.0")

        if limit < 1:
            raise ValueError("limit must be greater than 0")

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

            if similarity < threshold:
                continue

            similar_memories.append(
                {
                    "id": memory.id,
                    "memory": memory.memory_text,
                    "similarity": round(similarity, 4),
                }
            )

        return similar_memories

    def add_memory(
        self,
        user_id: str,
        memory_text: str,
        category: str,
        importance: str = "medium",
        dedup_threshold: float = 0.75,
    ) -> bool:
        """
        Add a long-term memory only when a sufficiently similar
        memory does not already exist for this user.
        """

        if not memory_text.strip():
            raise ValueError("memory_text cannot be empty")

        if not 0.0 <= dedup_threshold <= 1.0:
            raise ValueError(
                "dedup_threshold must be between 0.0 and 1.0"
            )

        with Session(engine) as session:
            # Exact duplicate check first.
            existing_memory = session.scalar(
                select(Memory).where(
                    Memory.user_id == user_id,
                    Memory.memory_text == memory_text,
                )
            )

            if existing_memory:
                return False

            # Generate the embedding only once.
            embedding = self.embedding_service.create_embedding(
                memory_text
            )

            embedding_list = embedding.tolist()

            # Semantic duplicate check.
            similar_memories = self._find_similar_by_embedding(
                session=session,
                user_id=user_id,
                query_embedding=embedding_list,
                threshold=dedup_threshold,
                limit=1,
            )

            # A sufficiently similar memory already exists.
            if similar_memories:
                return False

            # Save memory + embedding.
            memory = Memory(
                user_id=user_id,
                memory_text=memory_text,
                category=category,
                importance=importance,
                embedding=embedding_list,
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
        threshold: float = 0.70,
        limit: int = 8,
    ) -> list[dict]:
        """
        Find semantically similar memories using pgvector.
        """

        if not new_memory.strip():
            raise ValueError("new_memory cannot be empty")

        # Generate the query embedding once.
        query_embedding = (
            self.embedding_service
            .create_embedding(new_memory)
            .tolist()
        )

        with Session(engine) as session:
            # Enable iterative HNSW scans for filtered searches.
            session.execute(
                text(
                    "SET LOCAL hnsw.iterative_scan = strict_order"
                )
            )

            return self._find_similar_by_embedding(
                session=session,
                user_id=user_id,
                query_embedding=query_embedding,
                threshold=threshold,
                limit=limit,
            )

    def update_memory(
        self,
        memory_id: int,
        memory_text: str,
        category: str | None = None,
        importance: str | None = None,
    ) -> bool:
        if not memory_text.strip():
            raise ValueError("memory_text cannot be empty")

        with Session(engine) as session:
            memory = session.get(Memory, memory_id)

            if not memory:
                return False

            # Update text.
            memory.memory_text = memory_text

            # Regenerate embedding because text changed.
            embedding = self.embedding_service.create_embedding(
                memory_text
            )

            memory.embedding = embedding.tolist()

            # Update optional fields.
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
