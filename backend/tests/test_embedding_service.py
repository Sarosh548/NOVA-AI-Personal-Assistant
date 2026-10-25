import services.embedding_service as embedding_module


def test_embedding_service_reuses_one_model_for_multiple_instances(monkeypatch):
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
