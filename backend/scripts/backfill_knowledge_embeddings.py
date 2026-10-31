"""Backfill knowledge chunks created while semantic embeddings were unavailable."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.connection import engine
from models.knowledge_chunk import KnowledgeChunk
from services.embedding_service import EmbeddingService


def backfill_knowledge_embeddings(batch_size: int = 50) -> int:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")

    embedding_service = EmbeddingService()
    updated_count = 0

    while True:
        with Session(engine) as session:
            chunks = session.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.embedding.is_(None))
                .order_by(KnowledgeChunk.id.asc())
                .limit(batch_size)
            ).all()

            if not chunks:
                break

            for chunk in chunks:
                vector = embedding_service.create_embedding(chunk.content)
                chunk.embedding = (
                    vector.tolist()
                    if hasattr(vector, "tolist")
                    else list(vector)
                )

            # Commit each batch so a large knowledge base does not require
            # every embedding to remain in memory or one long transaction.
            session.commit()
            updated_count += len(chunks)
            print(
                f"Backfilled {updated_count} knowledge chunks so far."
            )

    print(
        f"Successfully backfilled {updated_count} knowledge chunk embeddings."
    )
    return updated_count


if __name__ == "__main__":
    backfill_knowledge_embeddings()
