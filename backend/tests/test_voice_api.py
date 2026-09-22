from __future__ import annotations

import asyncio
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


class FakeVoiceSTTOrchestrator:
    instances = []

    def __init__(
        self,
        *,
        adapter,
        settings,
    ):
        self.adapter = adapter
        self.settings = settings
        self.active = False
        self.turn_id = None
        self.audio_frames = []
        self.events_queue = asyncio.Queue()
        self.final_text = "hello world"
        self.instances.append(self)

    async def start_turn(
        self,
        *,
        user_id,
        session_id,
        turn_id,
        audio_format,
    ):
        self.active = True
        self.turn_id = turn_id
        self.user_id = user_id
        self.session_id = session_id
        self.audio_format = audio_format
        return "fake-stt-stream-1"

    async def send_audio(
        self,
        frame: bytes,
    ):
        self.audio_frames.append(frame)

        await self.events_queue.put(
            {
                "type": "transcript.partial",
                "stream_id": "fake-stt-stream-1",
                "turn_id": self.turn_id,
                "sequence": 1,
                "text": "hello",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )

    async def finish_turn(self):
        await self.events_queue.put(
            {
                "type": "transcript.final",
                "stream_id": "fake-stt-stream-1",
                "turn_id": self.turn_id,
                "sequence": 2,
                "text": self.final_text,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )

        return SimpleNamespace(
            type="final",
            text=self.final_text,
        )

    async def cancel_turn(self):
        self.active = False
        await self.events_queue.put(None)

    async def close_session(self):
        self.active = False
        await self.events_queue.put(None)

    async def events(self):
        while True:
            item = await self.events_queue.get()

            if item is None:
                return

            yield item


def _patch_auth(
    monkeypatch,
):
    import api.voice as voice_module

    monkeypatch.setattr(
        voice_module,
        "_resolve_authenticated_context",
        lambda _token: _fake_context(),
    )

    return voice_module


def _patch_fake_stt(
    monkeypatch,
):
    import api.voice as voice_module

    FakeVoiceSTTOrchestrator.instances = []

    monkeypatch.setattr(
        voice_module,
        "_build_voice_stt_orchestrator",
        lambda _settings: FakeVoiceSTTOrchestrator(
            adapter=object(),
            settings=_settings,
        ),
    )


def test_voice_websocket_handshake_and_turn_flow(
    monkeypatch,
):
    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)

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
                "audio_format": {
                    "encoding": "pcm_s16le",
                    "sample_rate_hz": 16_000,
                    "channels": 1,
                },
            }
        )

        started = websocket.receive_json()

        assert started["type"] == (
            "turn.started"
        )
        assert started["turn_id"] == (
            "turn-1"
        )
        assert started["stt_stream_id"] == (
            "fake-stt-stream-1"
        )

        websocket.send_bytes(
            b"12345678"
        )

        partial = websocket.receive_json()
        assert partial["type"] == "transcript.partial"
        assert partial["text"] == "hello"

        websocket.send_json(
            {
                "type": "turn.commit",
                "turn_id": "turn-1",
            }
        )

        final = websocket.receive_json()
        assert final["type"] == "transcript.final"
        assert final["text"] == "hello world"

        committed = websocket.receive_json()

        assert committed["type"] == (
            "turn.committed"
        )
        assert committed["turn_id"] == (
            "turn-1"
        )
        assert committed["audio_frames"] == 1
        assert committed["audio_bytes"] == 8
        assert committed["transcript"] == "hello world"

    assert FakeVoiceSTTOrchestrator.instances[0].audio_frames == [
        b"12345678"
    ]


def test_voice_websocket_supports_browser_style_authentication(
    monkeypatch,
):
    _patch_auth(monkeypatch)

    client = TestClient(
        _build_app()
    )

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
    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)

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
        websocket.receive_json()

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
    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)

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


def test_voice_websocket_rejects_audio_format_outside_turn_start(
    monkeypatch,
):
    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)

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
                "type": "session.ping",
                "audio_format": {
                    "encoding": "pcm_s16le",
                    "sample_rate_hz": 16_000,
                    "channels": 1,
                },
            }
        )

        error = websocket.receive_json()

        assert error["type"] == "error"
        assert error["code"] == (
            "invalid_control_message"
        )


def test_voice_websocket_requires_active_turn_for_audio(
    monkeypatch,
):
    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)

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
    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)

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
