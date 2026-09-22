import pytest

import database.connection as connection_module
from config import DatabaseSettings


def test_database_connect_timeout_has_bounded_default():
    settings = DatabaseSettings()

    assert settings.db_connect_timeout_seconds == 5


def test_database_connect_timeout_rejects_invalid_values():
    with pytest.raises(ValueError):
        DatabaseSettings(
            db_connect_timeout_seconds=0,
        )

    with pytest.raises(ValueError):
        DatabaseSettings(
            db_connect_timeout_seconds=61,
        )


def test_build_engine_passes_postgres_connect_timeout(
    monkeypatch,
):
    captured = {}

    class FakeEngine:
        pass

    def fake_create_engine(
        database_url,
        **kwargs,
    ):
        captured["database_url"] = database_url
        captured["kwargs"] = kwargs
        return FakeEngine()

    monkeypatch.setattr(
        connection_module,
        "create_engine",
        fake_create_engine,
    )

    engine = connection_module.build_engine(
        "postgresql+psycopg://example",
        7,
    )

    assert isinstance(
        engine,
        FakeEngine,
    )
    assert (
        captured["database_url"]
        == "postgresql+psycopg://example"
    )
    assert captured["kwargs"]["connect_args"] == {
        "connect_timeout": 7
    }
    assert captured["kwargs"]["pool_pre_ping"] is True
    assert captured["kwargs"]["pool_recycle"] == 1800
