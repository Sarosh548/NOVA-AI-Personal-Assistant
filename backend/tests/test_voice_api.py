from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.voice import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _fake_context(
    user_id: str = "voice-test-user",
):
    return SimpleNamespace(
        user=SimpleNamespace(
            id=user_id
        )
    )


def test_voice_websocket_handshake_and_turn_flow(
    monkeypatch,
):
    import api.voice as voice_module

    monkeypatch.setattr(
        voice_module,
        "_resolve_authenticated_context",
        lambda _token: _fake_context(),
    )

    client = TestClient(
        _build_app()
    )

    with client.websocket_connect(
        "/voice/ws",
        headers={
            "Authorization": "Bearer test-token",
        },
    ) as websocket:
        ready = websocket.receive_json()

        assert ready["type"] == (
            "session.ready"
        )
        assert ready["protocol_version"] == "1"
        assert ready["session_id"]

        websocket.send_json(
            {
                "type": "turn.start",
                "turn_id": "turn-1",
            }
        )

        started = websocket.receive_json()

        assert started["type"] == (
            "turn.started"
        )
        assert started["turn_id"] == (
            "turn-1"
        )

        websocket.send_bytes(
            b"12345678"
        )

        websocket.send_json(
            {
                "type": "turn.commit",
                "turn_id": "turn-1",
            }
        )

        committed = websocket.receive_json()

        assert committed["type"] == (
            "turn.committed"
        )
        assert committed["turn_id"] == (
            "turn-1"
        )
        assert committed["audio_frames"] == 1
        assert committed["audio_bytes"] == 8


def test_voice_websocket_supports_browser_style_authentication(
    monkeypatch,
):
    import api.voice as voice_module

    monkeypatch.setattr(
        voice_module,
        "_resolve_authenticated_context",
        lambda _token: _fake_context(),
    )

    client = TestClient(
        _build_app()
    )

    monkeypatch.setattr(
        voice_module,
        "get_security_settings",
        lambda: SimpleNamespace(
            cors_allowed_origins=lambda: (
                "https://app.example.com",
            )
        ),
    )

    with client.websocket_connect(
        "/voice/ws",
        headers={
            "Origin": "https://app.example.com",
        },
    ) as websocket:
        websocket.send_json(
            {
                "type": "session.authenticate",
                "access_token": "test-token",
            }
        )

        ready = websocket.receive_json()

        assert ready["type"] == (
            "session.ready"
        )
        assert ready["protocol_version"] == "1"
        assert ready["session_id"]


def test_voice_websocket_cancel_interrupts_active_turn(
    monkeypatch,
):
    import api.voice as voice_module

    monkeypatch.setattr(
        voice_module,
        "_resolve_authenticated_context",
        lambda _token: _fake_context(),
    )

    client = TestClient(
        _build_app()
    )

    with client.websocket_connect(
        "/voice/ws",
        headers={
            "Authorization": "Bearer test-token"
        },
    ) as websocket:
        websocket.receive_json()

        websocket.send_json(
            {
                "type": "turn.start",
                "turn_id": "turn-1",
            }
        )

        websocket.receive_json()

        websocket.send_bytes(
            b"audio"
        )

        websocket.send_json(
            {
                "type": "turn.cancel",
                "turn_id": "turn-1",
            }
        )

        cancelled = websocket.receive_json()

        assert cancelled == {
            "type": "turn.cancelled",
            "turn_id": "turn-1",
        }


def test_voice_websocket_rejects_missing_auth():
    client = TestClient(
        _build_app()
    )

    with client.websocket_connect(
        "/voice/ws"
    ) as websocket:
        websocket.send_json(
            {
                "type": "turn.start",
                "turn_id": "turn-1",
            }
        )

        error = websocket.receive_json()

        assert error["type"] == "error"
        assert error["code"] == (
            "authentication_required"
        )


def test_voice_websocket_rejects_invalid_control_message(
    monkeypatch,
):
    import api.voice as voice_module

    monkeypatch.setattr(
        voice_module,
        "_resolve_authenticated_context",
        lambda _token: _fake_context(),
    )

    client = TestClient(
        _build_app()
    )

    with client.websocket_connect(
        "/voice/ws",
        headers={
            "Authorization": "Bearer test-token"
        },
    ) as websocket:
        websocket.receive_json()

        websocket.send_text(
            '{"type":"not-a-real-message"}'
        )

        error = websocket.receive_json()

        assert error["type"] == "error"
        assert error["code"] == (
            "invalid_control_message"
        )


def test_voice_websocket_requires_active_turn_for_audio(
    monkeypatch,
):
    import api.voice as voice_module

    monkeypatch.setattr(
        voice_module,
        "_resolve_authenticated_context",
        lambda _token: _fake_context(),
    )

    client = TestClient(
        _build_app()
    )

    with client.websocket_connect(
        "/voice/ws",
        headers={
            "Authorization": "Bearer test-token"
        },
    ) as websocket:
        websocket.receive_json()

        websocket.send_bytes(
            b"audio"
        )

        error = websocket.receive_json()

        assert error["type"] == "error"
        assert error["code"] == (
            "no_active_turn"
        )


def test_voice_websocket_supports_ping_and_close(
    monkeypatch,
):
    import api.voice as voice_module

    monkeypatch.setattr(
        voice_module,
        "_resolve_authenticated_context",
        lambda _token: _fake_context(),
    )

    client = TestClient(
        _build_app()
    )

    with client.websocket_connect(
        "/voice/ws",
        headers={
            "Authorization": "Bearer test-token"
        },
    ) as websocket:
        ready = websocket.receive_json()

        websocket.send_json(
            {
                "type": "session.ping"
            }
        )

        pong = websocket.receive_json()

        assert pong["type"] == (
            "session.pong"
        )
        assert pong["session_id"] == (
            ready["session_id"]
        )

        websocket.send_json(
            {
                "type": "session.close"
            }
        )

        closed = websocket.receive_json()

        assert closed["type"] == (
            "session.closed"
        )
        assert closed["session_id"] == (
            ready["session_id"]
        )


def test_voice_websocket_rejects_unauthorized_origin(
    monkeypatch,
):
    import api.voice as voice_module

    monkeypatch.setattr(
        voice_module,
        "get_security_settings",
        lambda: SimpleNamespace(
            cors_allowed_origins=lambda: (
                "https://app.example.com",
            )
        ),
    )

    client = TestClient(
        _build_app()
    )

    with pytest.raises(
        WebSocketDisconnect
    ) as exc_info:
        with client.websocket_connect(
            "/voice/ws",
            headers={
                "Origin": "https://evil.example.com",
            },
        ):
            pass

    assert exc_info.value.code == 1008
