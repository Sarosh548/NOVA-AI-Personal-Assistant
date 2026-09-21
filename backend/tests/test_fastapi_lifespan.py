from fastapi.testclient import TestClient

import main


def test_app_uses_lifespan_for_startup_and_shutdown(
    monkeypatch,
):
    events = []

    async def fake_startup():
        events.append("startup")

    async def fake_shutdown():
        events.append("shutdown")

    monkeypatch.setattr(
        main,
        "startup_event",
        fake_startup,
    )
    monkeypatch.setattr(
        main,
        "shutdown_event",
        fake_shutdown,
    )

    with TestClient(main.app) as client:
        assert client.get("/").status_code == 200

    assert events == [
        "startup",
        "shutdown",
    ]
