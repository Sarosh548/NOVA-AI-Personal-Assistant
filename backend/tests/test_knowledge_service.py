from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import services.knowledge_service as knowledge_module
from models.knowledge_chunk import KnowledgeChunk
from services.knowledge_service import KnowledgeService


@dataclass
class FakeDocument:
    id: int = 7
    user_id: str = "user-001"
    title: str = "Python Guide"
    source: str | None = "manual"
    content: str = "Python is useful for AI development."
    content_hash: str = "h" * 64
    created_at: datetime = datetime(
        2026,
        9,
        20,
        10,
        0,
    )
    updated_at: datetime = datetime(
        2026,
        9,
        20,
        10,
        0,
    )


@dataclass
class FakeChunk:
    id: int = 11
    document_id: int = 7
    user_id: str = "user-001"
    chunk_index: int = 0
    content: str = "Python is useful for AI development."
    embedding: list[float] | None = None


class FakeVector:
    def tolist(self):
        return [0.1, 0.2, 0.3]


class FakeEmbedding:
    def create_embedding(self, text):
        return FakeVector()


class FakeSession:
    def __init__(
        self,
        engine,
        *,
        document=None,
        chunk_count=1,
        duplicate=None,
    ):
        self.engine = engine
        self.document = document
        self.chunk_count = chunk_count
        self.duplicate = duplicate
        self.added = []
        self.committed = False
        self.deleted = None

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        return False

    def scalar(self, statement):
        text = str(
            statement
        )

        if "count(" in text.lower():
            return self.chunk_count

        if "content_hash" in text:
            return self.duplicate

        params = statement.compile().params
        user_id = next(
            (
                value
                for value in params.values()
                if value in {
                    "user-001",
                    "user-002",
                }
            ),
            None,
        )

        if (
            user_id is not None
            and self.document is not None
            and self.document.user_id != user_id
        ):
            return None

        return self.document

    def flush(self):
        for item in self.added:
            if isinstance(
                item,
                FakeDocument,
            ):
                continue

        documents = [
            item
            for item in self.added
            if item.__class__.__name__
            == "KnowledgeDocument"
        ]

        if documents:
            documents[0].id = 7

    def add(self, item):
        self.added.append(item)

    def commit(self):
        self.committed = True

    def refresh(self, document):
        document.created_at = datetime(
            2026,
            9,
            20,
            10,
            0,
        )
        document.updated_at = datetime(
            2026,
            9,
            20,
            10,
            0,
        )

    def delete(self, document):
        self.deleted = document

    def scalars(self, statement):
        class Result:
            def all(inner_self):
                return []

        return Result()

    def execute(self, statement):
        class Result:
            def all(inner_self):
                return []

        return Result()


def make_service():
    service = KnowledgeService.__new__(
        KnowledgeService
    )
    service.embedding_service = FakeEmbedding()
    return service


def test_chunk_text_creates_overlapping_chunks():
    content = "word " * 400

    chunks = KnowledgeService._chunk_text(
        content,
        chunk_size=100,
        overlap=20,
    )

    assert len(chunks) > 1
    assert all(chunks)


def test_chunk_text_rejects_invalid_overlap():
    try:
        KnowledgeService._chunk_text(
            "hello",
            chunk_size=10,
            overlap=10,
        )
    except ValueError as exc:
        assert "overlap" in str(exc)
    else:
        raise AssertionError(
            "Expected ValueError"
        )


def test_create_document_persists_chunks(monkeypatch):
    session = FakeSession(
        None,
        chunk_count=2,
    )

    monkeypatch.setattr(
        knowledge_module,
        "Session",
        lambda engine: session,
    )

    service = make_service()

    result = service.create_document(
        user_id="user-001",
        title="Python Guide",
        content=(
            "Python is useful for AI development. "
            * 100
        ),
        source="manual",
    )

    assert result["id"] == 7
    assert result["title"] == "Python Guide"
    assert result["chunk_count"] >= 2
    assert session.committed is True
    assert any(
        item.__class__.__name__
        == "KnowledgeDocument"
        for item in session.added
    )
    assert any(
        isinstance(
            item,
            KnowledgeChunk,
        )
        for item in session.added
    )


def test_create_document_rejects_duplicate_content(
    monkeypatch,
):
    session = FakeSession(
        None,
        duplicate=FakeDocument(),
    )

    monkeypatch.setattr(
        knowledge_module,
        "Session",
        lambda engine: session,
    )

    service = make_service()

    try:
        service.create_document(
            user_id="user-001",
            title="Duplicate",
            content="Same content",
        )
    except ValueError as exc:
        assert "identical content" in str(exc)
    else:
        raise AssertionError(
            "Expected duplicate content rejection"
        )


def test_create_document_requires_content():
    service = make_service()

    try:
        service.create_document(
            user_id="user-001",
            title="Empty",
            content=" ",
        )
    except ValueError as exc:
        assert "content" in str(exc)
    else:
        raise AssertionError(
            "Expected content validation"
        )


def test_get_document_is_user_scoped(
    monkeypatch,
):
    session = FakeSession(
        None,
        document=FakeDocument(
            user_id="user-001"
        ),
    )

    monkeypatch.setattr(
        knowledge_module,
        "Session",
        lambda engine: session,
    )

    service = make_service()

    assert service.get_document(
        user_id="user-002",
        document_id=7,
    ) is None


def test_delete_document_is_user_scoped(
    monkeypatch,
):
    session = FakeSession(
        None,
        document=FakeDocument(
            user_id="user-001"
        ),
    )

    monkeypatch.setattr(
        knowledge_module,
        "Session",
        lambda engine: session,
    )

    service = make_service()

    assert service.delete_document(
        user_id="user-002",
        document_id=7,
    ) is False
    assert session.deleted is None


def test_delete_document_allows_owned_document(
    monkeypatch,
):
    document = FakeDocument(
        user_id="user-001"
    )

    session = FakeSession(
        None,
        document=document,
    )

    monkeypatch.setattr(
        knowledge_module,
        "Session",
        lambda engine: session,
    )

    service = make_service()

    assert service.delete_document(
        user_id="user-001",
        document_id=7,
    ) is True
    assert session.deleted is document
    assert session.committed is True


def test_search_query_contains_user_ownership_filters():
    service = make_service()

    vector = service.embedding_service.create_embedding(
        "python"
    ).tolist()

    distance_expression = (
        KnowledgeChunk.embedding.cosine_distance(
            vector
        )
    )

    from sqlalchemy import select

    statement = (
        select(
            KnowledgeChunk,
            distance_expression.label("distance"),
        )
        .join(
            knowledge_module.KnowledgeDocument,
            knowledge_module.KnowledgeDocument.id
            == KnowledgeChunk.document_id,
        )
        .where(
            KnowledgeChunk.user_id == "user-001",
            knowledge_module.KnowledgeDocument.user_id
            == "user-001",
        )
    )

    sql = str(
        statement
    )

    assert "knowledge_chunks.user_id" in sql
    assert "knowledge_documents.user_id" in sql


def test_search_validates_threshold(
    monkeypatch,
):
    monkeypatch.setattr(
        knowledge_module,
        "Session",
        lambda engine: FakeSession(None),
    )

    service = make_service()

    try:
        service.search(
            user_id="user-001",
            query="python",
            threshold=1.5,
        )
    except ValueError as exc:
        assert "threshold" in str(exc)
    else:
        raise AssertionError(
            "Expected threshold validation"
        )
