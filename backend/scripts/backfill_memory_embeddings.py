from sqlalchemy import select
from sqlalchemy.orm import Session

from database.connection import engine
from models.memory import Memory
from services.embedding_service import EmbeddingService


def backfill_memory_embeddings() -> None:
    embedding_service = EmbeddingService()

    with Session(engine) as session:
        statement = (
            select(Memory)
            .where(Memory.embedding.is_(None))
            .order_by(Memory.id)
        )

        memories = session.scalars(statement).all()

        print(f"Found {len(memories)} memories without embeddings.")

        updated_count = 0

        for memory in memories:
            embedding = embedding_service.create_embedding(
                memory.memory_text
            )

            memory.embedding = embedding.tolist()
            updated_count += 1

            print(
                f"Updated memory ID {memory.id}: "
                f"{memory.memory_text}"
            )

        session.commit()

        print(
            f"Successfully backfilled {updated_count} memory embeddings."
        )


if __name__ == "__main__":
    backfill_memory_embeddings()
