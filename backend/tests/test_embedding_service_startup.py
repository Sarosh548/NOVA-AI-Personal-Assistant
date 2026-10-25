import services.embedding_service as embedding_module


def test_embedding_service_loads_shared_model_only_on_first_use(monkeypatch):
    calls = []

    class FakeModel:
        def encode(self, text):
            return ("encoded", text)

    fake_model = FakeModel()

    monkeypatch.setattr(embedding_module, "_SHARED_MODEL", None)
    monkeypatch.setattr(
        embedding_module,
        "_load_model",
        lambda: calls.append("load") or fake_model,
    )

    first = embedding_module.EmbeddingService()
    second = embedding_module.EmbeddingService()

    # Creating global services at FastAPI import time must not load weights.
    assert calls == []

    assert first.create_embedding("hello") == ("encoded", "hello")
    assert calls == ["load"]

    # The loaded model is reused by every service instance.
    assert second.create_embedding("world") == ("encoded", "world")
    assert second.model is fake_model
    assert calls == ["load"]
