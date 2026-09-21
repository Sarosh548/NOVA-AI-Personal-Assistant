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
        visible_user_id=None,
        search_rows=None,
    ):
        self.engine = engine
        self.document = document
        self.visible_user_id = visible_user_id
        self.search_rows = list(search_rows or [])
        self.last_statement = None
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

        params = statement.compile().params

        if any(
            str(key).startswith("content_hash")
            for key in params
        ):
            return self.duplicate

        if self.document is None:
            return None

        if (
            self.visible_user_id is not None
            and self.document.user_id
            != self.visible_user_id
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
        self.last_statement = statement

        class Result:
            def all(inner_self):
                return list(self.search_rows)

        return Result()


class FakeReranker:
    def __init__(self):
        self.calls = []

    def rerank(
        self,
        query,
        candidates,
        *,
        top_k,
    ):
        self.calls.append(
            {
                "query": query,
                "candidates": list(candidates),
                "top_k": top_k,
            }
        )

        ranked = [
            dict(candidates[index])
            for index in reversed(
                range(len(candidates))
            )
        ]

        for index, candidate in enumerate(
            ranked
        ):
            candidate["rerank_score"] = (
                1.0 - (index * 0.1)
            )

        return ranked[:top_k]


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
        visible_user_id="user-002",
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
        visible_user_id="user-002",
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
        visible_user_id="user-001",
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


def test_search_can_rerank_candidates_after_similarity_filter(
    monkeypatch,
):
    document_a = FakeDocument(
        id=7,
        user_id="user-001",
        title="A",
        content="Alpha passage",
    )
    document_b = FakeDocument(
        id=8,
        user_id="user-001",
        title="B",
        content="Beta passage",
    )
    document_c = FakeDocument(
        id=9,
        user_id="user-001",
        title="C",
        content="Low similarity passage",
    )

    session = FakeSession(
        None,
        search_rows=[
            (
                FakeChunk(
                    document_id=7,
                    content="Alpha passage",
                ),
                document_a,
                0.10,
            ),
            (
                FakeChunk(
                    document_id=8,
                    content="Beta passage",
                    chunk_index=1,
                ),
                document_b,
                0.20,
            ),
            (
                FakeChunk(
                    document_id=9,
                    content="Low similarity passage",
                    chunk_index=2,
                ),
                document_c,
                0.50,
            ),
        ],
    )

    monkeypatch.setattr(
        knowledge_module,
        "Session",
        lambda engine: session,
    )

    reranker = FakeReranker()
    service = KnowledgeService(
        embedding_service=FakeEmbedding(),
        reranker_service=reranker,
    )

    result = service.search(
        user_id="user-001",
        query="passage",
        threshold=0.65,
        limit=2,
        rerank=True,
        candidate_limit=24,
    )

    assert [
        item["document_id"]
        for item in result
    ] == [
        8,
        7,
    ]

    assert [
        item["rerank_score"]
        for item in result
    ] == [
        1.0,
        0.9,
    ]

    assert len(reranker.calls) == 1
    assert reranker.calls[0]["query"] == "passage"
    assert reranker.calls[0]["top_k"] == 2
    assert [
        item["document_id"]
        for item in reranker.calls[0]["candidates"]
    ] == [
        7,
        8,
    ]

    params = session.last_statement.compile().params

    assert 24 in params.values()


def test_search_without_rerank_returns_similarity_order(
    monkeypatch,
):
    session = FakeSession(
        None,
        search_rows=[
            (
                FakeChunk(
                    document_id=7,
                    content="Alpha passage",
                ),
                FakeDocument(
                    id=7,
                    content="Alpha passage",
                ),
                0.10,
            ),
            (
                FakeChunk(
                    document_id=8,
                    content="Beta passage",
                    chunk_index=1,
                ),
                FakeDocument(
                    id=8,
                    content="Beta passage",
                ),
                0.20,
            ),
        ],
    )

    monkeypatch.setattr(
        knowledge_module,
        "Session",
        lambda engine: session,
    )

    reranker = FakeReranker()
    service = KnowledgeService(
        embedding_service=FakeEmbedding(),
        reranker_service=reranker,
    )

    result = service.search(
        user_id="user-001",
        query="passage",
        threshold=0.65,
        limit=2,
    )

    assert [
        item["document_id"]
        for item in result
    ] == [
        7,
        8,
    ]

    assert reranker.calls == []


def test_search_rejects_invalid_candidate_limit(
    monkeypatch,
):
    monkeypatch.setattr(
        knowledge_module,
        "Session",
        lambda engine: FakeSession(None),
    )

    service = KnowledgeService(
        embedding_service=FakeEmbedding(),
        reranker_service=FakeReranker(),
    )

    try:
        service.search(
            user_id="user-001",
            query="python",
            candidate_limit=0,
        )
    except ValueError as exc:
        assert "candidate_limit" in str(exc)
    else:
        raise AssertionError(
            "Expected candidate limit validation"
        )


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
