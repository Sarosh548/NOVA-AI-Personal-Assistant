from sqlalchemy import select, text
from sqlalchemy.orm import Session

from database.connection import engine
from models.memory import Memory
from services.embedding_service import EmbeddingService


# Similarity thresholds
MEMORY_MERGE_THRESHOLD = 0.90
MEMORY_RELATED_THRESHOLD = 0.75


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
    ) -> bool:
        """
        Save a new memory or safely update an existing near-duplicate.

        Behavior:
        - Exact duplicate -> ignore
        - Similarity >= 0.90 -> update existing memory
        - Similarity 0.75-0.90 -> treat as related and ignore
        - Similarity < 0.75 -> create new memory
        """

        if not memory_text.strip():
            raise ValueError("memory_text cannot be empty")

        with Session(engine) as session:
            # -------------------------------------------------
            # 1. Exact duplicate check
            # -------------------------------------------------
            existing_memory = session.scalar(
                select(Memory).where(
                    Memory.user_id == user_id,
                    Memory.memory_text == memory_text,
                )
            )

            if existing_memory:
                return False

            # -------------------------------------------------
            # 2. Create embedding once
            # -------------------------------------------------
            embedding = self.embedding_service.create_embedding(
                memory_text
            )

            embedding_list = embedding.tolist()

            # -------------------------------------------------
            # 3. Find related memories
            # -------------------------------------------------
            session.execute(
                text(
                    "SET LOCAL hnsw.iterative_scan = strict_order"
                )
            )

            similar_memories = self._find_similar_by_embedding(
                session=session,
                user_id=user_id,
                query_embedding=embedding_list,
                threshold=MEMORY_RELATED_THRESHOLD,
                limit=1,
            )

            # -------------------------------------------------
            # 4. No similar memory -> create new memory
            # -------------------------------------------------
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

            # -------------------------------------------------
            # 5. Similar memory found
            # -------------------------------------------------
            match = similar_memories[0]

            if match["similarity"] >= MEMORY_MERGE_THRESHOLD:
                # Strong duplicate:
                # update the existing memory with the new wording.
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

            # -------------------------------------------------
            # 6. Related but not identical:
            # do not overwrite or create another duplicate.
            # -------------------------------------------------
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
        """Find semantically similar memories using pgvector."""

        if not new_memory.strip():
            raise ValueError("new_memory cannot be empty")

        if not 0.0 <= threshold <= 1.0:
            raise ValueError(
                "threshold must be between 0.0 and 1.0"
            )

        if limit < 1:
            raise ValueError(
                "limit must be greater than 0"
            )

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