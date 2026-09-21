from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.health as health_module


def build_client():
    app = FastAPI()
    app.include_router(
        health_module.router
    )
    return TestClient(app)


def test_liveness_probe_is_available():
    client = build_client()

    response = client.get(
        "/health/live"
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok"
    }


def test_readiness_probe_reports_database_health(
    monkeypatch,
):
    client = build_client()

    monkeypatch.setattr(
        health_module,
        "test_connection",
        lambda: True,
    )

    response = client.get(
        "/health/ready"
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "ok",
    }


def test_readiness_probe_returns_503_when_database_fails(
    monkeypatch,
):
    client = build_client()

    def fail():
        raise RuntimeError(
            "database down"
        )

    monkeypatch.setattr(
        health_module,
        "test_connection",
        fail,
    )

    response = client.get(
        "/health/ready"
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Database is unavailable."
    }
