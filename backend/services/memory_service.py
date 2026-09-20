import re

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
    def __init__(
        self,
        llm_service: LLMService | None = None,
    ):
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

        distance_expression = (
            Memory.embedding.cosine_distance(
                query_embedding
            )
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

        results = session.execute(
            statement
        ).all()

        similar_memories = []

        for memory, distance in results:
            distance = float(distance)

            similarity = 1.0 - distance

            if similarity < threshold:
                continue

            importance_boost = (
                IMPORTANCE_BOOST.get(
                    memory.importance,
                    0.02,
                )
            )

            ranking_score = (
                similarity + importance_boost
            )

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

    # =========================================================
    # Explicit goal-change detection
    # =========================================================

    def _is_explicit_goal_change(
        self,
        user_message: str,
    ) -> bool:
        """
        Detect explicit language indicating that the user
        is changing or replacing a career/long-term goal.

        Examples that should return True:

            "I've changed my career goal."
            "I changed my goal and now I want to become..."
            "My new career goal is..."
            "I've switched my career goal to..."
            "I no longer want to become X."
            "My new goal is..."

        A normal new goal statement such as:

            "I want to become a Machine Learning Engineer."

        does NOT count as an explicit replacement.
        """

        if not user_message:
            return False

        text = user_message.strip().lower()

        if not text:
            return False

        change_patterns = (
            r"\bchanged?\b.*\bcareer goal\b",
            r"\bchanged?\b.*\bgoal\b",
            r"\bnew career goal\b",
            r"\bnew goal\b",
            r"\bswitched?\b.*\bcareer goal\b",
            r"\bswitched?\b.*\bgoal\b",
            r"\bchange(?:d)?\b.*\bcareer\b.*\bgoal\b",
            r"\bno longer\b.*\bwant\b.*\bbecome\b",
            r"\bno longer\b.*\bwant\b.*\bgoal\b",
            r"\bfrom\b.*\bto\b.*\bcareer goal\b",
        )

        return any(
            re.search(
                pattern,
                text,
            )
            for pattern in change_patterns
        )

    # =========================================================
    # Goal memory selection
    # =========================================================

    def _find_goal_memories(
        self,
        session: Session,
        user_id: str,
    ) -> list[Memory]:
        """
        Return existing goal memories for the user.

        New explicit goal-change requests use these memories
        as candidates for replacement.
        """

        statement = (
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.category == "goal",
            )
            .order_by(
                Memory.created_at.desc()
            )
        )

        return session.scalars(
            statement
        ).all()

    def _select_goal_memory_for_update(
        self,
        goal_memories: list[Memory],
    ) -> Memory | None:
        """
        Select the most appropriate existing career goal
        memory for replacement.

        We intentionally avoid automatically replacing
        interview-preparation memories because:

            "Preparing for an AI Engineer interview"

        is not necessarily the same thing as:

            "My career goal is AI Engineer."

        Preference:
            1. A direct career-goal memory
            2. Otherwise the most recent goal memory
        """

        if not goal_memories:
            return None

        direct_goal_phrases = (
            "career goal",
            "my goal",
            "wants to become",
            "want to become",
            "changed my goal",
            "new goal",
        )

        for memory in goal_memories:
            text_value = (
                memory.memory_text.lower()
            )

            if any(
                phrase in text_value
                for phrase in direct_goal_phrases
            ):
                return memory

        return goal_memories[0]

    # =========================================================
    # Main memory write operation
    # =========================================================

    def add_memory(
        self,
        user_id: str,
        memory_text: str,
        category: str,
        importance: str = "medium",
        user_message: str | None = None,
    ) -> str:
        """
        Add or update a long-term memory.

        Returns:
            CREATED
            UPDATED
            IGNORED

        `user_message` is optional for backward compatibility.

        When supplied, it allows the service to distinguish:

            "I want to become an ML Engineer."

        from:

            "I changed my career goal and now I want
             to become an ML Engineer."

        The second case is treated as an explicit
        replacement signal for goal memories.
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
            # 2. Explicit goal replacement
            # -------------------------------------------------

            if (
                category == "goal"
                and user_message
                and self._is_explicit_goal_change(
                    user_message
                )
            ):
                goal_memories = (
                    self._find_goal_memories(
                        session=session,
                        user_id=user_id,
                    )
                )

                target_memory = (
                    self._select_goal_memory_for_update(
                        goal_memories
                    )
                )

                if target_memory:
                    embedding = (
                        self.embedding_service
                        .create_embedding(
                            memory_text
                        )
                    )

                    embedding_list = (
                        embedding.tolist()
                    )

                    self._update_memory_row(
                        memory=target_memory,
                        memory_text=memory_text,
                        category=category,
                        importance=importance,
                        embedding=embedding_list,
                    )

                    session.commit()

                    return "UPDATED"

                # No previous goal exists.
                # Fall through to normal creation.

            # -------------------------------------------------
            # 3. Create embedding once
            # -------------------------------------------------

            embedding = (
                self.embedding_service
                .create_embedding(
                    memory_text
                )
            )

            embedding_list = embedding.tolist()

            # -------------------------------------------------
            # 4. Search related memories in SAME category
            # -------------------------------------------------

            session.execute(
                text(
                    "SET LOCAL hnsw.iterative_scan = strict_order"
                )
            )

            similar_memories = (
                self._find_similar_by_embedding(
                    session=session,
                    user_id=user_id,
                    query_embedding=embedding_list,
                    threshold=MEMORY_RELATED_THRESHOLD,
                    limit=5,
                    category=category,
                )
            )

            # -------------------------------------------------
            # 5. No related same-category memories
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
            # 6. Ask LLM to classify memory relationship
            # -------------------------------------------------

            strongest_match = (
                similar_memories[0]
            )

            candidate_text = "\n".join(
                f"{index}. {item['memory']}"
                for index, item in enumerate(
                    similar_memories,
                    start=1,
                )
            )

            decision = (
                self.llm_service
                .resolve_memory_conflict(
                    new_memory=memory_text,
                    new_category=category,
                    existing_memory=candidate_text,
                )
            )

            # -------------------------------------------------
            # 7. DUPLICATE
            # -------------------------------------------------

            if decision == "DUPLICATE":
                return "IGNORED"

            # -------------------------------------------------
            # 8. UPDATE
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
            # 9. KEEP / CREATE
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

    # =========================================================
    # Memory retrieval
    # =========================================================

    def list_memories(
        self,
        user_id: str,
        category: str | None = None,
        importance: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Return user-owned memories for management APIs.

        Results are scoped by user_id and optionally filtered by
        category and importance.
        """

        if limit < 1:
            raise ValueError(
                "limit must be greater than 0"
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

        if (
            category is not None
            and category not in valid_categories
        ):
            raise ValueError(
                "Invalid memory category."
            )

        valid_importance = {
            "high",
            "medium",
            "low",
        }

        if (
            importance is not None
            and importance not in valid_importance
        ):
            raise ValueError(
                "Invalid memory importance."
            )

        with Session(engine) as session:
            filters = [
                Memory.user_id == user_id,
            ]

            if category is not None:
                filters.append(
                    Memory.category == category
                )

            if importance is not None:
                filters.append(
                    Memory.importance == importance
                )

            statement = (
                select(Memory)
                .where(*filters)
                .order_by(
                    Memory.created_at.desc()
                )
                .limit(limit)
            )

            memories = session.scalars(
                statement
            ).all()

            return [
                {
                    "id": memory.id,
                    "memory": memory.memory_text,
                    "category": memory.category,
                    "importance": memory.importance,
                    "created_at": memory.created_at,
                    "updated_at": memory.updated_at,
                }
                for memory in memories
            ]

    def get_memory(
        self,
        user_id: str,
        memory_id: int,
    ) -> dict | None:
        """
        Return one memory only when it belongs to the user.
        """

        with Session(engine) as session:
            memory = session.scalar(
                select(Memory).where(
                    Memory.id == memory_id,
                    Memory.user_id == user_id,
                )
            )

            if memory is None:
                return None

            return {
                "id": memory.id,
                "memory": memory.memory_text,
                "category": memory.category,
                "importance": memory.importance,
                "created_at": memory.created_at,
                "updated_at": memory.updated_at,
            }

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
                .order_by(
                    Memory.created_at
                )
            )

            memories = session.scalars(
                statement
            ).all()

            return [
                memory.memory_text
                for memory in memories
            ]

    def get_profile_memories(
        self,
        user_id: str,
        limit: int = 20,
    ) -> list[dict]:
        """
        Retrieve stable profile-style memories.

        This is separate from semantic retrieval.

        It is useful for broad questions such as:
        - "Who am I?"
        - "What do you know about me?"
        - "What are my goals?"
        """

        if limit < 1:
            raise ValueError(
                "limit must be greater than 0"
            )

        profile_categories = {
            "identity",
            "personal",
            "goal",
            "preference",
            "project",
        }

        with Session(engine) as session:
            statement = (
                select(Memory)
                .where(
                    Memory.user_id == user_id,
                    Memory.category.in_(
                        profile_categories
                    ),
                )
                .order_by(
                    Memory.created_at.asc()
                )
                .limit(limit)
            )

            memories = session.scalars(
                statement
            ).all()

            return [
                {
                    "id": memory.id,
                    "memory": memory.memory_text,
                    "category": memory.category,
                    "importance": memory.importance,
                }
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
                .create_embedding(
                    memory_text
                )
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