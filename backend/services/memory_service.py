from sqlalchemy import select, text
from sqlalchemy.orm import Session

from database.connection import engine
from models.memory import Memory
from services.embedding_service import EmbeddingService
from services.llm_service import LLMService


MEMORY_RELATED_THRESHOLD = 0.60

IMPORTANCE_BOOST = {
    "high": 0.05,
    "medium": 0.02,
    "low": 0.00,
}


class MemoryService:
    def __init__(self, llm_service: LLMService | None = None):
        self.embedding_service = EmbeddingService()
        self.llm_service = llm_service or LLMService()

    def _find_similar_by_embedding(
        self,
        session: Session,
        user_id: str,
        query_embedding: list[float],
        threshold: float,
        limit: int = 10,
        category: str | None = None,
    ) -> list[dict]:
        """
        Find semantically similar memories.

        Similarity is used to find candidate memories.
        Importance provides a small ranking boost.
        """

        if not 0.0 <= threshold <= 1.0:
            raise ValueError(
                "threshold must be between 0.0 and 1.0"
            )

        if limit < 1:
            raise ValueError(
                "limit must be greater than 0"
            )

        distance_expression = Memory.embedding.cosine_distance(
            query_embedding
        )

        filters = [
            Memory.user_id == user_id,
            Memory.embedding.is_not(None),
        ]

        if category is not None:
            filters.append(
                Memory.category == category
            )

        statement = (
            select(
                Memory,
                distance_expression.label("distance"),
            )
            .where(*filters)
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
                    "similarity": round(
                        similarity,
                        4,
                    ),
                    "ranking_score": round(
                        ranking_score,
                        4,
                    ),
                }
            )

        similar_memories.sort(
            key=lambda item: item["ranking_score"],
            reverse=True,
        )

        return similar_memories[:limit]

    def _create_memory(
        self,
        session: Session,
        user_id: str,
        memory_text: str,
        category: str,
        importance: str,
        embedding: list[float],
    ) -> int:
        """Create a memory row and return its ID."""

        memory = Memory(
            user_id=user_id,
            memory_text=memory_text,
            category=category,
            importance=importance,
            embedding=embedding,
        )

        session.add(memory)
        session.flush()

        return memory.id

    def _update_memory_row(
        self,
        memory: Memory,
        memory_text: str,
        category: str,
        importance: str,
        embedding: list[float],
    ) -> None:
        """Update an existing memory row."""

        memory.memory_text = memory_text
        memory.category = category
        memory.importance = importance
        memory.embedding = embedding

    def add_memory(
        self,
        user_id: str,
        memory_text: str,
        category: str,
        importance: str = "medium",
    ) -> str:
        """
        Add or update a long-term memory.

        Returns:
            CREATED
            UPDATED
            IGNORED
        """

        if not memory_text.strip():
            raise ValueError(
                "memory_text cannot be empty"
            )

        valid_categories = {
            "identity",
            "goal",
            "preference",
            "project",
            "interest",
            "context",
            "personal",
        }

        if category not in valid_categories:
            category = "context"

        valid_importance = {
            "high",
            "medium",
            "low",
        }

        if importance not in valid_importance:
            importance = "medium"

        with Session(engine) as session:
            # -------------------------------------------------
            # 1. Exact duplicate
            # -------------------------------------------------
            existing_memory = session.scalar(
                select(Memory).where(
                    Memory.user_id == user_id,
                    Memory.memory_text == memory_text,
                )
            )

            if existing_memory:
                return "IGNORED"

            # -------------------------------------------------
            # 2. Create embedding once
            # -------------------------------------------------
            embedding = (
                self.embedding_service
                .create_embedding(memory_text)
            )

            embedding_list = embedding.tolist()

            # -------------------------------------------------
            # 3. Search related memories in the SAME category
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
                limit=5,
                category=category,
            )

            # -------------------------------------------------
            # 4. No related same-category memories
            # -------------------------------------------------
            if not similar_memories:
                self._create_memory(
                    session=session,
                    user_id=user_id,
                    memory_text=memory_text,
                    category=category,
                    importance=importance,
                    embedding=embedding_list,
                )

                session.commit()

                return "CREATED"

            # -------------------------------------------------
            # 5. Ask LLM to classify the memory relationship
            # -------------------------------------------------
            strongest_match = similar_memories[0]

            candidate_text = "\n".join(
                f"{index}. {item['memory']}"
                for index, item in enumerate(
                    similar_memories,
                    start=1,
                )
            )

            decision = self.llm_service.resolve_memory_conflict(
                new_memory=memory_text,
                new_category=category,
                existing_memory=candidate_text,
            )

            # -------------------------------------------------
            # 6. DUPLICATE
            # -------------------------------------------------
            if decision == "DUPLICATE":
                return "IGNORED"

            # -------------------------------------------------
            # 7. UPDATE
            # -------------------------------------------------
            if decision == "UPDATE":
                memory = session.get(
                    Memory,
                    strongest_match["id"],
                )

                if not memory:
                    return "IGNORED"

                self._update_memory_row(
                    memory=memory,
                    memory_text=memory_text,
                    category=category,
                    importance=importance,
                    embedding=embedding_list,
                )

                session.commit()

                return "UPDATED"

            # -------------------------------------------------
            # 8. KEEP / CREATE
            # -------------------------------------------------
            self._create_memory(
                session=session,
                user_id=user_id,
                memory_text=memory_text,
                category=category,
                importance=importance,
                embedding=embedding_list,
            )

            session.commit()

            return "CREATED"

    def get_memories(
        self,
        user_id: str,
    ) -> list[str]:

        with Session(engine) as session:
            statement = (
                select(Memory)
                .where(
                    Memory.user_id == user_id
                )
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
        threshold: float = 0.65,
        limit: int = 8,
    ) -> list[dict]:
        """
        Find relevant memories using semantic similarity
        plus importance-aware ranking.

        This method is for retrieval/inspection only.
        It does not decide whether memories should be merged.
        """

        if not new_memory.strip():
            raise ValueError(
                "new_memory cannot be empty"
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
            raise ValueError(
                "memory_text cannot be empty"
            )

        with Session(engine) as session:
            memory = session.get(
                Memory,
                memory_id,
            )

            if not memory:
                return False

            embedding = (
                self.embedding_service
                .create_embedding(memory_text)
            )

            memory.memory_text = memory_text
            memory.embedding = embedding.tolist()

            if category is not None:
                memory.category = category

            if importance is not None:
                if importance not in {
                    "high",
                    "medium",
                    "low",
                }:
                    importance = "medium"

                memory.importance = importance

            session.commit()

            return True

    def delete_memory(
        self,
        memory_id: int,
    ) -> bool:

        with Session(engine) as session:
            memory = session.get(
                Memory,
                memory_id,
            )

            if not memory:
                return False

            session.delete(memory)
            session.commit()

            return True