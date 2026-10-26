import pytest

import services.embedding_service as embedding_module


def test_embedding_service_reuses_one_model_for_multiple_instances(monkeypatch):
    monkeypatch.setenv("NOVA_LOCAL_EMBEDDINGS_ENABLED", "true")
    calls = []
    fake_model = type(
        "FakeModel",
        (),
        {"encode": lambda self, text: ("encoded", text)},
    )()

    def fake_load_model():
        calls.append(embedding_module._MODEL_NAME)
        return fake_model

    monkeypatch.setattr(embedding_module, "_SHARED_MODEL", None)
    monkeypatch.setattr(embedding_module, "_load_model", fake_load_model)

    first = embedding_module.EmbeddingService()
    second = embedding_module.EmbeddingService()

    # Model initialization must remain deferred until an embedding is needed.
    assert calls == []
    assert first.model is fake_model
    assert calls == ["all-MiniLM-L6-v2"]
    assert second.model is fake_model
    assert first.create_embedding("hello") == ("encoded", "hello")
    assert second.create_embedding("world") == ("encoded", "world")



def test_embedding_service_skips_transformer_import_when_container_memory_is_too_small(monkeypatch):
    monkeypatch.delenv("NOVA_LOCAL_EMBEDDINGS_ENABLED", raising=False)
    monkeypatch.setattr(
        embedding_module,
        "_container_memory_limit_bytes",
        lambda: 512 * 1024 * 1024,
    )
    monkeypatch.setattr(embedding_module, "_SHARED_MODEL", None)

    def should_not_load_model():
        raise AssertionError("Transformer model must not load on a 512 MiB container")

    monkeypatch.setattr(embedding_module, "_load_model", should_not_load_model)

    with pytest.raises(embedding_module.EmbeddingUnavailableError, match="keyword retrieval"):
        embedding_module.EmbeddingService().create_embedding("QA-only: calculate 17 times 6")


def test_explicit_embedding_enable_override_is_respected(monkeypatch):
    monkeypatch.setenv("NOVA_LOCAL_EMBEDDINGS_ENABLED", "true")
    monkeypatch.setattr(
        embedding_module,
        "_container_memory_limit_bytes",
        lambda: 512 * 1024 * 1024,
    )

    assert embedding_module.local_embeddings_enabled() is True



def test_embedding_service_wraps_model_download_or_initialization_failures(monkeypatch):
    monkeypatch.setenv("NOVA_LOCAL_EMBEDDINGS_ENABLED", "true")
    monkeypatch.setattr(embedding_module, "_SHARED_MODEL", None)

    def fail_to_load():
        raise OSError("simulated model download failure")

    monkeypatch.setattr(embedding_module, "_load_model", fail_to_load)
    with pytest.raises(embedding_module.EmbeddingUnavailableError, match="keyword retrieval"):
        embedding_module.EmbeddingService().create_embedding("hello")
