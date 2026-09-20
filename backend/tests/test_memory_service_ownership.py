from __future__ import annotations

from dataclasses import dataclass

import services.memory_service as memory_module
from services.memory_service import MemoryService


@dataclass
class FakeMemory:
    id: int = 7
    user_id: str = "user-001"
    memory_text: str = "User prefers Python."
    category: str = "preference"
    importance: str = "medium"
    created_at: object = None
    updated_at: object = None
    embedding: list[float] | None = None


class FakeVector:
    def tolist(self):
        return [0.1, 0.2, 0.3]


class FakeEmbedding:
    def create_embedding(self, text):
        return FakeVector()


class FakeSession:
    memory = None
    deleted = None
    committed = False

    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def scalar(self, statement):
        return self.memory

    def commit(self):
        self.committed = True

    def delete(self, memory):
        self.deleted = memory


def make_service():
    service = MemoryService.__new__(
        MemoryService
    )
    service.embedding_service = FakeEmbedding()
    return service


def test_get_memory_is_user_scoped(monkeypatch):
    session = FakeSession(None)
    session.memory = FakeMemory(
        user_id="user-001"
    )

    monkeypatch.setattr(
        memory_module,
        "Session",
        lambda engine: session,
    )

    service = make_service()

    assert service.get_memory(
        user_id="user-002",
        memory_id=7,
    ) is None


def test_update_memory_is_user_scoped(monkeypatch):
    session = FakeSession(None)
    session.memory = None

    monkeypatch.setattr(
        memory_module,
        "Session",
        lambda engine: session,
    )

    service = make_service()

    assert service.update_memory(
        user_id="user-002",
        memory_id=7,
        memory_text="Changed memory",
    ) is False


def test_update_memory_allows_owned_memory(monkeypatch):
    session = FakeSession(None)
    session.memory = FakeMemory(
        user_id="user-001"
    )

    monkeypatch.setattr(
        memory_module,
        "Session",
        lambda engine: session,
    )

    service = make_service()

    assert service.update_memory(
        user_id="user-001",
        memory_id=7,
        memory_text="Changed memory",
        importance="high",
    ) is True
    assert session.memory.memory_text == (
        "Changed memory"
    )
    assert session.memory.importance == "high"
    assert session.committed is True


def test_delete_memory_is_user_scoped(monkeypatch):
    session = FakeSession(None)
    session.memory = None

    monkeypatch.setattr(
        memory_module,
        "Session",
        lambda engine: session,
    )

    service = make_service()

    assert service.delete_memory(
        user_id="user-002",
        memory_id=7,
    ) is False
    assert session.deleted is None


def test_delete_memory_allows_owned_memory(monkeypatch):
    session = FakeSession(None)
    session.memory = FakeMemory(
        user_id="user-001"
    )

    monkeypatch.setattr(
        memory_module,
        "Session",
        lambda engine: session,
    )

    service = make_service()

    assert service.delete_memory(
        user_id="user-001",
        memory_id=7,
    ) is True
    assert session.deleted is session.memory
    assert session.committed is True
