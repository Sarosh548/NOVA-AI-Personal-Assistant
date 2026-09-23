from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.voice import router
from services.voice_tts_orchestrator import (
    VoiceTTSOrchestratorError,
)


class FakeVoiceConversationExecutionService:
    def __init__(self):
        self.calls = []
        self.block_first_execution = False
        self.first_execution_started = threading.Event()
        self.release_first_execution = threading.Event()
        self.response_payload = {
            "response": "Sure, done.",
            "conversation_id": 42,
            "confirmation": {
                "id": None,
                "status": None,
                "tool": None,
                "action": None,
                "reason": None,
            },
        }

    def prepare_conversation(
        self,
        *,
        user_id,
        conversation_id,
    ):
        return conversation_id or 42

    def execute_message(
        self,
        *,
        user_id,
        message,
        conversation_id,
        execution_context,
        on_response_delta=None,
        is_execution_current=None,
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "message": message,
                "conversation_id": conversation_id,
                "execution_context": execution_context,
                "on_response_delta": on_response_delta,
                "is_execution_current": is_execution_current,
            }
        )

        if (
            self.block_first_execution
            and len(self.calls) == 1
        ):
            self.first_execution_started.set()
            self.release_first_execution.wait(
                timeout=5
            )

            if on_response_delta is not None:
                try:
                    on_response_delta("stale")
                except Exception:
                    pass

        if on_response_delta is not None:
            try:
                on_response_delta("Sure, ")
                on_response_delta("done.")
            except Exception:
                pass

        return dict(self.response_payload)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.state.conversation_execution_service = (
        FakeVoiceConversationExecutionService()
    )
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
        self.emit_end_of_speech = False
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
                "is_end_of_speech": False,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )

        if self.emit_end_of_speech:
            await self.events_queue.put(
                {
                    "type": "transcript.final",
                    "stream_id": "fake-stt-stream-1",
                    "turn_id": self.turn_id,
                    "sequence": 2,
                    "text": self.final_text,
                    "is_end_of_speech": True,
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


class FakeVoiceTTSOrchestrator:
    instances = []

    def __init__(
        self,
        *,
        adapter,
        settings,
    ):
        self.adapter = adapter
        self.settings = settings
        self.turn_id = None
        self.stream_id = "fake-tts-stream-1"
        self.events_queue = asyncio.Queue()
        self.texts = []
        self.instances.append(self)

    async def start_turn(
        self,
        *,
        user_id,
        session_id,
        turn_id,
        voice,
        audio_format,
    ):
        self.user_id = user_id
        self.session_id = session_id
        self.turn_id = turn_id
        self.voice = voice
        self.audio_format = audio_format
        return self.stream_id

    async def send_text(
        self,
        text,
    ):
        self.text = text
        self.texts.append(text)
        await self.events_queue.put(
            SimpleNamespace(
                type="audio",
                stream_id=self.stream_id,
                turn_id=self.turn_id,
                sequence=1,
                audio=b"tts-audio",
                created_at=SimpleNamespace(
                    isoformat=lambda: "2026-01-01T00:00:00+00:00"
                ),
            )
        )

    async def finish_turn(self):
        await self.events_queue.put(
            SimpleNamespace(
                type="final",
                stream_id=self.stream_id,
                turn_id=self.turn_id,
                sequence=2,
                audio=b"",
                created_at=SimpleNamespace(
                    isoformat=lambda: "2026-01-01T00:00:00+00:00"
                ),
            )
        )

    async def cancel_turn(self):
        await self.events_queue.put(None)

    async def close_session(self):
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


def _patch_fake_tts(
    monkeypatch,
):
    import api.voice as voice_module

    FakeVoiceTTSOrchestrator.instances = []

    monkeypatch.setattr(
        voice_module,
        "_build_voice_tts_orchestrator",
        lambda _settings: FakeVoiceTTSOrchestrator(
            adapter=object(),
            settings=_settings,
        ),
    )

    monkeypatch.setattr(
        voice_module,
        "get_tts_provider_settings",
        lambda: SimpleNamespace(
            elevenlabs_voice_id="voice/example",
        ),
    )


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

        assistant = websocket.receive_json()

        assert assistant["type"] == "assistant.response"
        assert assistant["turn_id"] == "turn-1"
        assert assistant["conversation_id"] == 42
        assert assistant["response"] == "Sure, done."
        assert assistant["confirmation"]["status"] is None

    core_service = websocket.app.state.conversation_execution_service

    assert core_service.calls[0]["user_id"] == "voice-test-user"
    assert core_service.calls[0]["message"] == "hello world"
    assert core_service.calls[0]["conversation_id"] == 42
    assert isinstance(
        core_service.calls[0]["execution_context"],
        object,
    )

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


def test_voice_websocket_keeps_conversation_for_follow_up_turn(
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
        websocket.receive_json()

        websocket.send_json(
            {
                "type": "turn.start",
                "turn_id": "turn-1",
            }
        )
        websocket.receive_json()

        websocket.send_bytes(b"first")
        websocket.receive_json()

        websocket.send_json(
            {
                "type": "turn.commit",
                "turn_id": "turn-1",
            }
        )

        first_final = websocket.receive_json()
        assert first_final["type"] == "transcript.final"

        first_committed = websocket.receive_json()
        assert first_committed["type"] == "turn.committed"
        assert first_committed["turn_id"] == "turn-1"

        first_assistant = websocket.receive_json()
        assert first_assistant["type"] == "assistant.response"
        assert first_assistant["turn_id"] == "turn-1"

        websocket.send_json(
            {
                "type": "turn.start",
                "turn_id": "turn-2",
            }
        )
        websocket.receive_json()

        websocket.send_bytes(b"second")
        websocket.receive_json()

        websocket.send_json(
            {
                "type": "turn.commit",
                "turn_id": "turn-2",
            }
        )

        second_final = websocket.receive_json()
        assert second_final["type"] == "transcript.final"
        assert second_final["turn_id"] == "turn-2"

        second_committed = websocket.receive_json()
        assert second_committed["type"] == "turn.committed"
        assert second_committed["turn_id"] == "turn-2"

        assistant = websocket.receive_json()
        assert assistant["type"] == "assistant.response"
        assert assistant["conversation_id"] == 42

    core_service = client.app.state.conversation_execution_service

    assert len(core_service.calls) == 2
    assert core_service.calls[0]["conversation_id"] == 42
    assert core_service.calls[1]["conversation_id"] == 42


def test_voice_websocket_barge_in_cancels_previous_response_and_accepts_new_turn(
    monkeypatch,
):
    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)
    _patch_fake_tts(monkeypatch)

    client = TestClient(
        _build_app()
    )

    core_service = client.app.state.conversation_execution_service
    core_service.block_first_execution = True

    with client.websocket_connect(
        "/voice/ws",
        headers={
            "Authorization": "Bearer test-token",
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

        websocket.send_bytes(b"first")
        websocket.receive_json()

        websocket.send_json(
            {
                "type": "turn.commit",
                "turn_id": "turn-1",
            }
        )

        assert websocket.receive_json()["type"] == "transcript.final"
        assert websocket.receive_json()["type"] == "turn.committed"
        assert websocket.receive_json()["type"] == "assistant.audio.started"

        assert core_service.first_execution_started.wait(
            timeout=2
        )

        websocket.send_json(
            {
                "type": "turn.start",
                "turn_id": "turn-2",
            }
        )

        cancelled = websocket.receive_json()
        assert cancelled == {
            "type": "assistant.audio.cancelled",
        }

        second_started = websocket.receive_json()
        assert second_started["type"] == "turn.started"
        assert second_started["turn_id"] == "turn-2"

        websocket.send_bytes(b"second")
        websocket.receive_json()

        websocket.send_json(
            {
                "type": "turn.commit",
                "turn_id": "turn-2",
            }
        )

        assert websocket.receive_json()["type"] == "transcript.final"
        assert websocket.receive_json()["type"] == "turn.committed"
        assert websocket.receive_json()["type"] == "assistant.audio.started"

        assistant = None

        while assistant is None:
            message = websocket.receive()

            if message.get("bytes") is not None:
                continue

            payload = json.loads(
                message["text"]
            )

            if payload["type"] == "assistant.response":
                assistant = payload
                continue

            if payload["type"] == "error":
                raise AssertionError(
                    f"Unexpected voice error: {payload!r}"
                )

        assert assistant["turn_id"] == "turn-2"
        assert assistant["conversation_id"] == 42

        core_service.release_first_execution.set()

        websocket.send_json(
            {
                "type": "session.ping",
            }
        )

        while True:
            message = websocket.receive()

            if message.get("bytes") is not None:
                continue

            payload = json.loads(
                message["text"]
            )

            if payload["type"] == "session.pong":
                pong = payload
                break

            if payload["type"] == "error":
                raise AssertionError(
                    f"Unexpected voice error: {payload!r}"
                )

        assert pong["type"] == "session.pong"

    fake_tts = FakeVoiceTTSOrchestrator.instances[0]
    assert fake_tts.texts == [
        "Sure, ",
        "done.",
    ]
    assert len(core_service.calls) == 2


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


def test_voice_websocket_cancel_interrupts_in_flight_assistant_response(
    monkeypatch,
):
    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)
    _patch_fake_tts(monkeypatch)

    client = TestClient(
        _build_app()
    )

    core_service = client.app.state.conversation_execution_service
    core_service.block_first_execution = True

    with client.websocket_connect(
        "/voice/ws",
        headers={
            "Authorization": "Bearer test-token",
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

        websocket.send_bytes(b"first")
        websocket.receive_json()

        websocket.send_json(
            {
                "type": "turn.commit",
                "turn_id": "turn-1",
            }
        )

        assert websocket.receive_json()["type"] == "transcript.final"
        assert websocket.receive_json()["type"] == "turn.committed"
        assert websocket.receive_json()["type"] == "assistant.audio.started"

        assert core_service.first_execution_started.wait(
            timeout=2
        )

        websocket.send_json(
            {
                "type": "turn.cancel",
                "turn_id": "turn-1",
            }
        )

        cancelled_audio = websocket.receive_json()
        assert cancelled_audio == {
            "type": "assistant.audio.cancelled",
        }

        cancelled_turn = websocket.receive_json()
        assert cancelled_turn == {
            "type": "turn.cancelled",
            "turn_id": "turn-1",
        }

        core_service.release_first_execution.set()

        websocket.send_json(
            {
                "type": "turn.start",
                "turn_id": "turn-2",
            }
        )

        second_started = websocket.receive_json()
        assert second_started["type"] == "turn.started"
        assert second_started["turn_id"] == "turn-2"

        websocket.send_bytes(b"second")
        assert websocket.receive_json()["type"] == "transcript.partial"

        websocket.send_json(
            {
                "type": "turn.commit",
                "turn_id": "turn-2",
            }
        )

        assert websocket.receive_json()["type"] == "transcript.final"
        assert websocket.receive_json()["type"] == "turn.committed"
        assert websocket.receive_json()["type"] == "assistant.audio.started"

        assistant = None

        while assistant is None:
            message = websocket.receive()

            if message.get("bytes") is not None:
                continue

            payload = json.loads(
                message["text"]
            )

            if payload["type"] == "assistant.response":
                assistant = payload
                continue

            if payload["type"] == "error":
                raise AssertionError(
                    f"Unexpected voice error: {payload!r}"
                )

        assert assistant["turn_id"] == "turn-2"
        assert assistant["conversation_id"] == 42

    assert len(core_service.calls) == 2

    fake_tts = FakeVoiceTTSOrchestrator.instances[0]
    assert fake_tts.texts == [
        "Sure, ",
        "done.",
    ]


def test_voice_websocket_auto_commits_on_end_of_speech(
    monkeypatch,
):
    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)
    _patch_fake_tts(monkeypatch)

    client = TestClient(
        _build_app()
    )

    with client.websocket_connect(
        "/voice/ws",
        headers={
            "Authorization": "Bearer test-token",
        },
    ) as websocket:
        websocket.receive_json()

        websocket.send_json(
            {
                "type": "turn.start",
                "turn_id": "turn-auto-1",
            }
        )

        started = websocket.receive_json()

        assert started["type"] == "turn.started"
        assert started["turn_id"] == "turn-auto-1"

        FakeVoiceSTTOrchestrator.instances[0].emit_end_of_speech = True

        websocket.send_bytes(
            b"input-audio"
        )

        seen_types = []
        assistant = None

        while assistant is None:
            message = websocket.receive()

            if message.get("bytes") is not None:
                continue

            payload = json.loads(
                message["text"]
            )
            seen_types.append(payload["type"])

            if payload["type"] == "assistant.response":
                assistant = payload
                continue

            if payload["type"] == "error":
                raise AssertionError(
                    f"Unexpected voice error: {payload!r}"
                )

        assert "transcript.partial" in seen_types
        assert "transcript.final" in seen_types
        assert "turn.committed" in seen_types
        assert assistant["turn_id"] == "turn-auto-1"
        assert assistant["response"] == "Sure, done."

        core_service = (
            websocket.app.state.conversation_execution_service
        )

        assert len(core_service.calls) == 1


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


def test_voice_websocket_streams_assistant_audio(
    monkeypatch,
):
    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)
    _patch_fake_tts(monkeypatch)

    client = TestClient(
        _build_app()
    )

    with client.websocket_connect(
        "/voice/ws",
        headers={
            "Authorization": "Bearer test-token",
        },
    ) as websocket:
        websocket.receive_json()

        websocket.send_json(
            {
                "type": "turn.start",
                "turn_id": "turn-tts-1",
            }
        )
        websocket.receive_json()

        websocket.send_bytes(
            b"input-audio"
        )
        websocket.receive_json()

        websocket.send_json(
            {
                "type": "turn.commit",
                "turn_id": "turn-tts-1",
            }
        )

        assert websocket.receive_json()["type"] == "transcript.final"
        assert websocket.receive_json()["type"] == "turn.committed"

        started = websocket.receive_json()
        assert started == {
            "type": "assistant.audio.started",
            "stream_id": "fake-tts-stream-1",
            "turn_id": "turn-tts-1",
            "audio_format": {
                "encoding": "pcm_s16le",
                "sample_rate_hz": 16_000,
                "channels": 1,
            },
        }

        messages = []

        while len(messages) < 4:
            message = websocket.receive()

            if message.get("bytes") is not None:
                messages.append(
                    {
                        "kind": "bytes",
                        "value": message["bytes"],
                    }
                )
                continue

            if message.get("text") is not None:
                messages.append(
                    {
                        "kind": "json",
                        "value": json.loads(
                            message["text"]
                        ),
                    }
                )
                continue

            raise AssertionError(
                f"Unexpected WebSocket message: {message!r}"
            )

        json_messages = [
            item["value"]
            for item in messages
            if item["kind"] == "json"
        ]

        assert any(
            message["type"] == "assistant.response"
            and message["response"] == "Sure, done."
            for message in json_messages
        )

        assert any(
            message["type"] == "assistant.audio.final"
            and message["stream_id"] == "fake-tts-stream-1"
            and message["turn_id"] == "turn-tts-1"
            and message["sequence"] == 2
            for message in json_messages
        )

        audio_messages = [
            item["value"]
            for item in messages
            if item["kind"] == "bytes"
        ]
        assert audio_messages == [
            b"tts-audio",
            b"tts-audio",
        ]

    fake_tts = FakeVoiceTTSOrchestrator.instances[0]
    assert fake_tts.voice == "voice/example"
    assert fake_tts.texts == [
        "Sure, ",
        "done.",
    ]

    core_service = websocket.app.state.conversation_execution_service
    assert callable(
        core_service.calls[0]["on_response_delta"]
    )


def test_voice_websocket_audio_output_failure_does_not_break_session(
    monkeypatch,
):
    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)
    _patch_fake_tts(monkeypatch)

    async def failing_send_text(self, _text):
        raise VoiceTTSOrchestratorError(
            "tts unavailable"
        )

    monkeypatch.setattr(
        FakeVoiceTTSOrchestrator,
        "send_text",
        failing_send_text,
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
        websocket.receive_json()

        websocket.send_json(
            {
                "type": "turn.start",
                "turn_id": "turn-tts-failure",
            }
        )
        websocket.receive_json()

        websocket.send_bytes(
            b"input-audio"
        )
        websocket.receive_json()

        websocket.send_json(
            {
                "type": "turn.commit",
                "turn_id": "turn-tts-failure",
            }
        )

        assert websocket.receive_json()["type"] == "transcript.final"
        assert websocket.receive_json()["type"] == "turn.committed"

        started = websocket.receive_json()
        assert started["type"] == "assistant.audio.started"

        messages = []

        while True:
            message = websocket.receive_json()
            messages.append(message)

            types = {
                item["type"]
                for item in messages
            }

            if (
                "assistant.response" in types
                and "error" in types
            ):
                break

            if len(messages) > 4:
                raise AssertionError(
                    f"Unexpected assistant message sequence: {messages!r}"
                )

        assert any(
            message["type"] == "assistant.response"
            for message in messages
        )

        error_messages = [
            message
            for message in messages
            if message["type"] == "error"
        ]
        assert error_messages
        assert error_messages[0]["code"] == "assistant_audio_failed"

        websocket.send_json(
            {
                "type": "session.ping",
            }
        )
        pong = websocket.receive_json()
        assert pong["type"] == "session.pong"

