from sqlalchemy import select, text
from sqlalchemy.orm import Session

from database.connection import engine
from models.memory import Memory
from services.embedding_service import EmbeddingService


MEMORY_MERGE_THRESHOLD = 0.90
MEMORY_RELATED_THRESHOLD = 0.75

IMPORTANCE_BOOST = {
    "high": 0.05,
    "medium": 0.02,
    "low": 0.00,
}


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
        """Find semantically similar memories for a user."""

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

            importance_boost = IMPORTANCE_BOOST.get(
                memory.importance,
                0.02,
            )

            ranking_score = similarity + importance_boost

            similar_memories.append(
                {
                    "id": memory.id,
                    "memory": memory.memory_text,
                    "category": memory.category,
                    "importance": memory.importance,
                    "similarity": round(similarity, 4),
                    "ranking_score": round(ranking_score, 4),
                }
            )

        # Similarity remains the main signal.
        # Importance only gives a small ranking advantage.
        similar_memories.sort(
            key=lambda item: item["ranking_score"],
            reverse=True,
        )

        return similar_memories[:limit]

    def add_memory(
        self,
        user_id: str,
        memory_text: str,
        category: str,
        importance: str = "medium",
    ) -> bool:
        """
        Save a new memory or safely update an existing near-duplicate.
        """

        if not memory_text.strip():
            raise ValueError("memory_text cannot be empty")

        valid_importance = {
            "high",
            "medium",
            "low",
        }

        if importance not in valid_importance:
            importance = "medium"

        with Session(engine) as session:
            # Exact duplicate check.
            existing_memory = session.scalar(
                select(Memory).where(
                    Memory.user_id == user_id,
                    Memory.memory_text == memory_text,
                )
            )

            if existing_memory:
                return False

            # Generate embedding once.
            embedding = self.embedding_service.create_embedding(
                memory_text
            )

            embedding_list = embedding.tolist()

            # Enable iterative HNSW scans.
            session.execute(
                text(
                    "SET LOCAL hnsw.iterative_scan = strict_order"
                )
            )

            # Find related memories.
            similar_memories = self._find_similar_by_embedding(
                session=session,
                user_id=user_id,
                query_embedding=embedding_list,
                threshold=MEMORY_RELATED_THRESHOLD,
                limit=1,
            )

            # No related memory -> create new memory.
            if not similar_memories:
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

            match = similar_memories[0]

            # Strong duplicate -> update existing memory.
            if match["similarity"] >= MEMORY_MERGE_THRESHOLD:
                memory = session.get(
                    Memory,
                    match["id"],
                )

                if not memory:
                    return False

                memory.memory_text = memory_text
                memory.embedding = embedding_list
                memory.category = category
                memory.importance = importance

                session.commit()

                return True

            # Related but not strong enough to merge.
            return False

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
        """Find relevant memories using similarity + importance ranking."""

        if not new_memory.strip():
            raise ValueError("new_memory cannot be empty")

        query_embedding = (
            self.embedding_service
            .create_embedding(new_memory)
            .tolist()
        )

        with Session(engine) as session:
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

            memory.memory_text = memory_text

            embedding = self.embedding_service.create_embedding(
                memory_text
            )

            memory.embedding = embedding.tolist()

            if category is not None:
                memory.category = category

            if importance is not None:
                if importance not in {"high", "medium", "low"}:
                    importance = "medium"

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