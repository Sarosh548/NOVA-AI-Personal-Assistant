from __future__ import annotations

import hashlib

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.connection import engine
from models.knowledge_chunk import KnowledgeChunk
from models.knowledge_document import KnowledgeDocument
from services.embedding_service import EmbeddingService


MAX_TITLE_LENGTH = 300
MAX_SOURCE_LENGTH = 1000
MAX_CONTENT_LENGTH = 250_000

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200

DEFAULT_SEARCH_THRESHOLD = 0.65
DEFAULT_SEARCH_LIMIT = 8


class KnowledgeService:
    """
    Durable user-scoped knowledge-base ingestion and retrieval.

    This first RAG foundation accepts normalized plain text.
    Parsing external files or URLs is intentionally kept outside
    this service until the storage and retrieval boundary is stable.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
    ):
        self.embedding_service = (
            embedding_service
            or EmbeddingService()
        )

    @staticmethod
    def _normalize_text(
        value: str,
        field_name: str,
        max_length: int,
    ) -> str:
        normalized = str(value).strip()

        if not normalized:
            raise ValueError(
                f"{field_name} cannot be empty."
            )

        if len(normalized) > max_length:
            raise ValueError(
                f"{field_name} exceeds the maximum length of "
                f"{max_length} characters."
            )

        return normalized

    @staticmethod
    def _content_hash(
        content: str,
    ) -> str:
        return hashlib.sha256(
            content.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _chunk_text(
        content: str,
        *,
        chunk_size: int = CHUNK_SIZE,
        overlap: int = CHUNK_OVERLAP,
    ) -> list[str]:
        if chunk_size < 1:
            raise ValueError(
                "chunk_size must be greater than 0"
            )

        if overlap < 0 or overlap >= chunk_size:
            raise ValueError(
                "overlap must be between 0 and chunk_size - 1"
            )

        chunks: list[str] = []
        start = 0
        content_length = len(content)

        while start < content_length:
            end = min(
                start + chunk_size,
                content_length,
            )

            if end < content_length:
                whitespace = content.rfind(
                    " ",
                    start,
                    end,
                )

                if whitespace > start + (chunk_size // 2):
                    end = whitespace

            chunk = content[start:end].strip()

            if chunk:
                chunks.append(chunk)

            if end >= content_length:
                break

            next_start = end - overlap

            if next_start <= start:
                next_start = end

            start = next_start

        return chunks

    @staticmethod
    def _document_payload(
        document: KnowledgeDocument,
        *,
        chunk_count: int,
        include_content: bool = False,
    ) -> dict:
        payload = {
            "id": document.id,
            "title": document.title,
            "source": document.source,
            "chunk_count": chunk_count,
            "created_at": document.created_at,
            "updated_at": document.updated_at,
        }

        if include_content:
            payload["content"] = document.content

        return payload

    def _chunk_count(
        self,
        session: Session,
        document_id: int,
    ) -> int:
        count = session.scalar(
            select(
                func.count(KnowledgeChunk.id)
            ).where(
                KnowledgeChunk.document_id
                == document_id
            )
        )

        return int(count or 0)

    def create_document(
        self,
        *,
        user_id: str,
        title: str,
        content: str,
        source: str | None = None,
    ) -> dict:
        normalized_title = self._normalize_text(
            title,
            "title",
            MAX_TITLE_LENGTH,
        )

        normalized_content = self._normalize_text(
            content,
            "content",
            MAX_CONTENT_LENGTH,
        )

        normalized_source = (
            None
            if source is None
            else self._normalize_text(
                source,
                "source",
                MAX_SOURCE_LENGTH,
            )
        )

        chunks = self._chunk_text(
            normalized_content
        )

        if not chunks:
            raise ValueError(
                "content does not contain any usable text."
            )

        content_hash = self._content_hash(
            normalized_content
        )

        with Session(engine) as session:
            duplicate = session.scalar(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.user_id
                    == user_id,
                    KnowledgeDocument.content_hash
                    == content_hash,
                )
            )

            if duplicate is not None:
                raise ValueError(
                    "A document with identical content "
                    "already exists."
                )

            document = KnowledgeDocument(
                user_id=user_id,
                title=normalized_title,
                source=normalized_source,
                content=normalized_content,
                content_hash=content_hash,
            )

            session.add(document)
            session.flush()

            for index, chunk_text in enumerate(
                chunks
            ):
                vector = (
                    self.embedding_service
                    .create_embedding(chunk_text)
                )

                embedding = (
                    vector.tolist()
                    if hasattr(
                        vector,
                        "tolist",
                    )
                    else list(vector)
                )

                session.add(
                    KnowledgeChunk(
                        document_id=document.id,
                        user_id=user_id,
                        chunk_index=index,
                        content=chunk_text,
                        embedding=embedding,
                    )
                )

            session.commit()
            session.refresh(document)

            return self._document_payload(
                document,
                chunk_count=len(chunks),
            )

    def list_documents(
        self,
        *,
        user_id: str,
        limit: int = 50,
    ) -> list[dict]:
        if limit < 1:
            raise ValueError(
                "limit must be greater than 0"
            )

        with Session(engine) as session:
            statement = (
                select(KnowledgeDocument)
                .where(
                    KnowledgeDocument.user_id
                    == user_id,
                )
                .order_by(
                    KnowledgeDocument.updated_at.desc()
                )
                .limit(limit)
            )

            documents = session.scalars(
                statement
            ).all()

            return [
                self._document_payload(
                    document,
                    chunk_count=self._chunk_count(
                        session,
                        document.id,
                    ),
                )
                for document in documents
            ]

    def get_document(
        self,
        *,
        user_id: str,
        document_id: int,
        include_content: bool = True,
    ) -> dict | None:
        with Session(engine) as session:
            document = session.scalar(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.id
                    == document_id,
                    KnowledgeDocument.user_id
                    == user_id,
                )
            )

            if document is None:
                return None

            return self._document_payload(
                document,
                chunk_count=self._chunk_count(
                    session,
                    document.id,
                ),
                include_content=include_content,
            )

    def delete_document(
        self,
        *,
        user_id: str,
        document_id: int,
    ) -> bool:
        with Session(engine) as session:
            document = session.scalar(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.id
                    == document_id,
                    KnowledgeDocument.user_id
                    == user_id,
                )
            )

            if document is None:
                return False

            session.delete(document)
            session.commit()

            return True

    def search(
        self,
        *,
        user_id: str,
        query: str,
        threshold: float = DEFAULT_SEARCH_THRESHOLD,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[dict]:
        normalized_query = self._normalize_text(
            query,
            "query",
            MAX_CONTENT_LENGTH,
        )

        if not 0.0 <= threshold <= 1.0:
            raise ValueError(
                "threshold must be between 0.0 and 1.0"
            )

        if limit < 1:
            raise ValueError(
                "limit must be greater than 0"
            )

        vector = (
            self.embedding_service.create_embedding(
                normalized_query
            )
        )

        query_embedding = (
            vector.tolist()
            if hasattr(
                vector,
                "tolist",
            )
            else list(vector)
        )

        distance_expression = (
            KnowledgeChunk.embedding.cosine_distance(
                query_embedding
            )
        )

        statement = (
            select(
                KnowledgeChunk,
                KnowledgeDocument,
                distance_expression.label(
                    "distance"
                ),
            )
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id
                == KnowledgeChunk.document_id,
            )
            .where(
                KnowledgeChunk.user_id
                == user_id,
                KnowledgeDocument.user_id
                == user_id,
                KnowledgeChunk.embedding.is_not(
                    None
                ),
            )
            .order_by(
                distance_expression
            )
            .limit(limit)
        )

        with Session(engine) as session:
            results = session.execute(
                statement
            ).all()

            matches: list[dict] = []

            for chunk, document, distance in results:
                similarity = 1.0 - float(
                    distance
                )

                if similarity < threshold:
                    continue

                matches.append(
                    {
                        "document_id": document.id,
                        "title": document.title,
                        "source": document.source,
                        "chunk_index": chunk.chunk_index,
                        "content": chunk.content,
                        "similarity": round(
                            similarity,
                            4,
                        ),
                    }
                )

            return matches
