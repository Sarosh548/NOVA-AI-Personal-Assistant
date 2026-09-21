from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from api.auth import get_token_service, router as auth_router
from api.knowledge import router as knowledge_router
from api.memories import router as memory_router
from config import Settings
from database.connection import engine
from models.auth_identity import AuthIdentity
from models.knowledge_chunk import KnowledgeChunk
from models.knowledge_document import KnowledgeDocument
from models.memory import Memory
from models.user import User
from models.user_session import UserSession
from services.embedding_service import EmbeddingService
from services.token_service import TokenService


PASSWORD = "CorrectPassword123!"
TEST_EMBEDDING = [1.0] + [0.0] * 383


class FakeEmbedding:
    def tolist(self):
        return list(TEST_EMBEDDING)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(memory_router)
    app.include_router(knowledge_router)

    token_service = TokenService(
        settings=Settings(
            auth_jwt_secret_key="x" * 64,
            auth_jwt_algorithm="HS256",
            auth_jwt_issuer="nova-api-test",
            auth_jwt_audience="nova-client-test",
            auth_access_token_expire_minutes=10,
        )
    )
    app.dependency_overrides[get_token_service] = lambda: token_service
    return app


def _register(client: TestClient, label: str) -> dict[str, str]:
    identifier = f"isolation-{label}-{uuid4().hex[:12]}@example.test"
    response = client.post(
        "/auth/register",
        json={
            "identifier": identifier,
            "password": PASSWORD,
            "display_name": f"Isolation {label}",
        },
    )
    assert response.status_code == 201
    body = response.json()
    return {
        "id": body["user"]["id"],
        "access_token": body["access_token"],
    }


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_memory(user_id: str, text_value: str) -> int:
    memory = Memory(
        user_id=user_id,
        memory_text=text_value,
        category="preference",
        importance="high",
        created_at=_now(),
        updated_at=_now(),
        embedding=list(TEST_EMBEDDING),
    )
    with Session(engine) as session:
        session.add(memory)
        session.flush()
        memory_id = memory.id
        session.commit()
    return memory_id


def _seed_document(user_id: str, title: str, content: str) -> int:
    document = KnowledgeDocument(
        user_id=user_id,
        title=title,
        source="authenticated-isolation-test",
        content=content,
        content_hash=uuid4().hex + uuid4().hex,
        created_at=_now(),
        updated_at=_now(),
    )
    with Session(engine) as session:
        session.add(document)
        session.flush()
        session.add(
            KnowledgeChunk(
                document_id=document.id,
                user_id=user_id,
                chunk_index=0,
                content=content,
                embedding=list(TEST_EMBEDDING),
                created_at=_now(),
            )
        )
        document_id = document.id
        session.commit()
    return document_id


def _cleanup(user_id: str) -> None:
    with Session(engine) as session:
        session.execute(delete(KnowledgeChunk).where(
            KnowledgeChunk.user_id == user_id
        ))
        session.execute(delete(KnowledgeDocument).where(
            KnowledgeDocument.user_id == user_id
        ))
        session.execute(delete(Memory).where(
            Memory.user_id == user_id
        ))
        session.execute(delete(UserSession).where(
            UserSession.user_id == user_id
        ))
        session.execute(delete(AuthIdentity).where(
            AuthIdentity.user_id == user_id
        ))
        session.execute(delete(User).where(
            User.id == user_id
        ))
        session.commit()


def test_authenticated_users_are_isolated_for_memory_and_knowledge(
    monkeypatch,
):
    monkeypatch.setattr(
        EmbeddingService,
        "__init__",
        lambda self: None,
    )
    monkeypatch.setattr(
        EmbeddingService,
        "create_embedding",
        lambda self, text: FakeEmbedding(),
    )

    app = _app()
    client = TestClient(app)

    user_a = _register(client, "a")
    user_b = _register(client, "b")

    try:
        memory_a = _seed_memory(
            user_a["id"],
            "User A private preference.",
        )
        memory_b = _seed_memory(
            user_b["id"],
            "User B private preference.",
        )
        document_a = _seed_document(
            user_a["id"],
            "User A Private Knowledge",
            "User A private knowledge content.",
        )
        document_b = _seed_document(
            user_b["id"],
            "User B Private Knowledge",
            "User B private knowledge content.",
        )

        headers_a = _headers(user_a["access_token"])
        headers_b = _headers(user_b["access_token"])

        memories_b = client.get(
            "/memories",
            headers=headers_b,
        )
        assert memories_b.status_code == 200
        ids_b = {item["id"] for item in memories_b.json()}
        assert memory_b in ids_b
        assert memory_a not in ids_b

        search_b = client.get(
            "/memories/search",
            headers=headers_b,
            params={"query": "private preference"},
        )
        assert search_b.status_code == 200
        search_ids_b = {item["id"] for item in search_b.json()}
        assert memory_b in search_ids_b
        assert memory_a not in search_ids_b

        assert client.get(
            f"/memories/{memory_a}",
            headers=headers_b,
        ).status_code == 404

        assert client.patch(
            f"/memories/{memory_a}",
            headers=headers_b,
            json={"memory": "Cross-user update attempt."},
        ).status_code == 404

        assert client.delete(
            f"/memories/{memory_a}",
            headers=headers_b,
        ).status_code == 404

        documents_b = client.get(
            "/knowledge/documents",
            headers=headers_b,
        )
        assert documents_b.status_code == 200
        document_ids_b = {
            item["id"] for item in documents_b.json()
        }
        assert document_b in document_ids_b
        assert document_a not in document_ids_b

        knowledge_search_b = client.get(
            "/knowledge/search",
            headers=headers_b,
            params={"query": "private knowledge"},
        )
        assert knowledge_search_b.status_code == 200
        search_document_ids_b = {
            item["document_id"]
            for item in knowledge_search_b.json()
        }
        assert document_b in search_document_ids_b
        assert document_a not in search_document_ids_b

        assert client.get(
            f"/knowledge/documents/{document_a}",
            headers=headers_b,
        ).status_code == 404

        assert client.delete(
            f"/knowledge/documents/{document_a}",
            headers=headers_b,
        ).status_code == 404

        assert client.get(
            f"/knowledge/documents/{document_b}",
            headers=headers_a,
        ).status_code == 404

    finally:
        _cleanup(user_a["id"])
        _cleanup(user_b["id"])
