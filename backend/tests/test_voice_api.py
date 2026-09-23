from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.voice import (
    VoiceWebSocketSendError,
    router,
)
from services.stt_adapter import (
    STTAdapter,
    STTAudioFormat,
    STTStream,
    STTStreamRequest,
    STTSpeechStartedEvent,
    STTTranscriptEvent,
    utc_now,
)
from services.tts_adapter import (
    TTSAudioEvent,
    TTSAudioFormat,
    TTSAdapter,
    TTSStream,
    TTSStreamRequest,
)
from services.voice_stt_orchestrator import (
    VoiceSTTOrchestrator,
    VoiceSTTOrchestratorError,
)
from services.voice_tts_orchestrator import (
    VoiceTTSOrchestrator,
    VoiceTTSOrchestratorError,
)


class BlockingVoiceWebSocket:
    def __init__(self, *, block_close=False):
        self.closed_code = None
        self.block_close = block_close

    async def send_json(self, _payload):
        await asyncio.sleep(1)

    async def send_bytes(self, _payload):
        await asyncio.sleep(1)

    async def close(self, *, code):
        self.closed_code = code
        if self.block_close:
            await asyncio.sleep(1)


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


class RecordingVoiceMetrics:
    def __init__(self):
        self.stt_finalization = []
        self.llm_first_delta = []
        self.tts_first_audio = []
        self.turn_response = []
        self.turn_total = []
        self.provider_events = []
        self.errors = []

    def observe_stt_finalization(self, duration_seconds):
        self.stt_finalization.append(duration_seconds)

    def observe_llm_first_delta(self, duration_seconds):
        self.llm_first_delta.append(duration_seconds)

    def observe_tts_first_audio(self, duration_seconds):
        self.tts_first_audio.append(duration_seconds)

    def observe_turn_response(self, duration_seconds):
        self.turn_response.append(duration_seconds)

    def observe_turn_total(self, duration_seconds):
        self.turn_total.append(duration_seconds)

    def record_provider_event(self, *, provider, event):
        self.provider_events.append((provider, event))

    def record_error(self, *, stage, code):
        self.errors.append((stage, code))



class FakeVoiceSessionLeaseService:
    active_sessions = {}
    instances = []

    def __init__(
        self,
        *,
        lease_seconds,
    ):
        self.lease_seconds = lease_seconds
        self.heartbeat_calls = 0
        self.heartbeat_result = True
        self.heartbeat_event = threading.Event()
        self.instances.append(self)

    def acquire(
        self,
        *,
        user_id,
        session_id,
    ):
        from types import SimpleNamespace

        active_session_id = self.active_sessions.get(
            user_id
        )

        if active_session_id is not None:
            return SimpleNamespace(
                acquired=False,
                lease_until=None,
                retry_after_seconds=23,
            )

        self.active_sessions[user_id] = session_id

        return SimpleNamespace(
            acquired=True,
            lease_until=None,
            retry_after_seconds=0,
        )

    def heartbeat(
        self,
        *,
        user_id,
        session_id,
    ):
        self.heartbeat_calls += 1
        self.heartbeat_event.set()

        if not self.heartbeat_result:
            return False

        return self.active_sessions.get(
            user_id
        ) == session_id

    def release(
        self,
        *,
        user_id,
        session_id,
    ):
        if (
            self.active_sessions.get(user_id)
            != session_id
        ):
            return False

        del self.active_sessions[user_id]
        return True


class FakeVoiceRateLimitService:
    instances = []

    def __init__(self):
        self.calls = []
        self.instances.append(self)

    def check_and_consume(
        self,
        *,
        principal_key,
        scope,
        limit,
        window_seconds,
    ):
        self.calls.append(
            {
                "principal_key": principal_key,
                "scope": scope,
                "limit": limit,
                "window_seconds": window_seconds,
            }
        )

        if len(self.calls) == 1:
            return SimpleNamespace(
                allowed=True,
                limit=limit,
                remaining=limit - 1,
                reset_after_seconds=60,
            )

        return SimpleNamespace(
            allowed=False,
            limit=limit,
            remaining=0,
            reset_after_seconds=17,
        )


def test_websocket_json_send_fails_fast_on_deadline(monkeypatch):
    import api.voice as voice_module

    timeout_settings = voice_module.get_voice_settings().model_copy(
        update={
            "voice_websocket_send_timeout_seconds": 0.01,
        }
    )
    monkeypatch.setattr(
        voice_module,
        "get_voice_settings",
        lambda: timeout_settings,
    )

    websocket = BlockingVoiceWebSocket()

    with pytest.raises(
        VoiceWebSocketSendError,
        match="send deadline",
    ):
        asyncio.run(
            voice_module._send_websocket_json(
                websocket,
                {"type": "test"},
            )
        )

    assert websocket.closed_code == 1011


def test_websocket_json_send_does_not_wait_for_blocked_close(monkeypatch):
    import api.voice as voice_module

    timeout_settings = voice_module.get_voice_settings().model_copy(
        update={
            "voice_websocket_send_timeout_seconds": 0.01,
        }
    )
    monkeypatch.setattr(
        voice_module,
        "get_voice_settings",
        lambda: timeout_settings,
    )

    websocket = BlockingVoiceWebSocket(
        block_close=True
    )

    with pytest.raises(
        VoiceWebSocketSendError,
        match="send deadline",
    ):
        asyncio.run(
            asyncio.wait_for(
                voice_module._send_websocket_json(
                    websocket,
                    {"type": "test"},
                ),
                timeout=0.2,
            )
        )

    assert websocket.closed_code == 1011


def test_websocket_bytes_send_does_not_wait_for_blocked_close(monkeypatch):
    import api.voice as voice_module

    timeout_settings = voice_module.get_voice_settings().model_copy(
        update={
            "voice_websocket_send_timeout_seconds": 0.01,
        }
    )
    monkeypatch.setattr(
        voice_module,
        "get_voice_settings",
        lambda: timeout_settings,
    )

    websocket = BlockingVoiceWebSocket(
        block_close=True
    )

    with pytest.raises(
        VoiceWebSocketSendError,
        match="send deadline",
    ):
        asyncio.run(
            asyncio.wait_for(
                voice_module._send_websocket_bytes(
                    websocket,
                    b"audio",
                ),
                timeout=0.2,
            )
        )

    assert websocket.closed_code == 1011


def test_websocket_bytes_send_fails_fast_on_deadline(monkeypatch):
    import api.voice as voice_module

    timeout_settings = voice_module.get_voice_settings().model_copy(
        update={
            "voice_websocket_send_timeout_seconds": 0.01,
        }
    )
    monkeypatch.setattr(
        voice_module,
        "get_voice_settings",
        lambda: timeout_settings,
    )

    websocket = BlockingVoiceWebSocket()

    with pytest.raises(
        VoiceWebSocketSendError,
        match="send deadline",
    ):
        asyncio.run(
            voice_module._send_websocket_bytes(
                websocket,
                b"audio",
            )
        )

    assert websocket.closed_code == 1011


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
        self.emit_utterance_end = False
        self.emit_error = False
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

        if self.emit_utterance_end:
            await self.events_queue.put(
                {
                    "type": "transcript.final",
                    "stream_id": "fake-stt-stream-1",
                    "turn_id": self.turn_id,
                    "sequence": 2,
                    "text": self.final_text,
                    "is_end_of_speech": False,
                    "created_at": "2026-01-01T00:00:00+00:00",
                }
            )
            await self.events_queue.put(
                {
                    "type": "transcript.utterance_end",
                    "stream_id": "fake-stt-stream-1",
                    "turn_id": self.turn_id,
                    "sequence": 3,
                    "last_word_end_seconds": 1.5,
                    "created_at": "2026-01-01T00:00:00+00:00",
                }
            )

        if self.emit_error:
            await self.events_queue.put(
                VoiceSTTOrchestratorError(
                    "STT provider disconnected mid-turn."
                )
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

            if isinstance(item, Exception):
                raise item

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
        self.emit_error = False
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

        if self.emit_error:
            await self.events_queue.put(
                VoiceTTSOrchestratorError(
                    "TTS provider disconnected mid-response."
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

            if isinstance(item, Exception):
                raise item

            yield item


class E2EVoiceSTTStream(STTStream):
    def __init__(
        self,
        *,
        stream_id: str,
        turn_id: str,
    ) -> None:
        self._stream_id = stream_id
        self._turn_id = turn_id
        self.audio_frames = []
        self.finished = False
        self.cancelled = False
        self.closed = False
        self._events = asyncio.Queue()

    @property
    def stream_id(self) -> str:
        return self._stream_id

    @property
    def turn_id(self) -> str:
        return self._turn_id

    async def send_audio(
        self,
        frame: bytes,
    ) -> None:
        self.audio_frames.append(frame)

        await self._events.put(
            STTSpeechStartedEvent(
                stream_id=self._stream_id,
                turn_id=self._turn_id,
                sequence=1,
                created_at=utc_now(),
            )
        )

        await self._events.put(
            STTTranscriptEvent(
                stream_id=self._stream_id,
                turn_id=self._turn_id,
                sequence=2,
                type="partial",
                text="hello",
                created_at=utc_now(),
            )
        )

    async def events(self):
        while True:
            item = await self._events.get()

            if item is None:
                return

            yield item

    async def finish(self) -> None:
        if self.finished:
            return

        self.finished = True

        await self._events.put(
            STTTranscriptEvent(
                stream_id=self._stream_id,
                turn_id=self._turn_id,
                sequence=3,
                type="final",
                text="hello world",
                is_end_of_speech=True,
                created_at=utc_now(),
            )
        )
        await self._events.put(None)

    async def cancel(self) -> None:
        self.cancelled = True
        await self._events.put(None)

    async def close(self) -> None:
        self.closed = True


class E2EVoiceSTTAdapter(STTAdapter):
    def __init__(self) -> None:
        self.stream: E2EVoiceSTTStream | None = None
        self.requests: list[STTStreamRequest] = []

    async def start_stream(
        self,
        request: STTStreamRequest,
    ) -> STTStream:
        self.requests.append(request)

        self.stream = E2EVoiceSTTStream(
            stream_id="e2e-stt-stream-1",
            turn_id=request.turn_id,
        )
        return self.stream


class E2EVoiceTTSStream(TTSStream):
    def __init__(
        self,
        *,
        stream_id: str,
        turn_id: str,
    ) -> None:
        self._stream_id = stream_id
        self._turn_id = turn_id
        self.text_chunks = []
        self.finished = False
        self.cancelled = False
        self.closed = False
        self._sequence = 0
        self._events = asyncio.Queue()

    @property
    def stream_id(self) -> str:
        return self._stream_id

    @property
    def turn_id(self) -> str:
        return self._turn_id

    async def send_text(
        self,
        text: str,
    ) -> None:
        self.text_chunks.append(text)
        self._sequence += 1

        await self._events.put(
            TTSAudioEvent(
                stream_id=self._stream_id,
                turn_id=self._turn_id,
                sequence=self._sequence,
                type="audio",
                audio=f"audio-{self._sequence}".encode(),
                created_at=utc_now(),
            )
        )

    async def events(self):
        while True:
            item = await self._events.get()

            if item is None:
                return

            yield item

    async def finish(self) -> None:
        if self.finished:
            return

        self.finished = True

        await self._events.put(
            TTSAudioEvent(
                stream_id=self._stream_id,
                turn_id=self._turn_id,
                sequence=self._sequence + 1,
                type="final",
                audio=b"",
                created_at=utc_now(),
            )
        )
        await self._events.put(None)

    async def cancel(self) -> None:
        self.cancelled = True
        await self._events.put(None)

    async def close(self) -> None:
        self.closed = True


class E2EVoiceTTSAdapter(TTSAdapter):
    def __init__(self) -> None:
        self.stream: E2EVoiceTTSStream | None = None
        self.requests: list[TTSStreamRequest] = []

    async def start_stream(
        self,
        request: TTSStreamRequest,
    ) -> TTSStream:
        self.requests.append(request)

        self.stream = E2EVoiceTTSStream(
            stream_id="e2e-tts-stream-1",
            turn_id=request.turn_id,
        )
        return self.stream


def _patch_auth(
    monkeypatch,
):
    import api.voice as voice_module

    monkeypatch.setattr(
        voice_module,
        "_resolve_authenticated_context",
        lambda _token: _fake_context(),
    )

    FakeVoiceSessionLeaseService.instances = []
    FakeVoiceSessionLeaseService.active_sessions = {}

    monkeypatch.setattr(
        voice_module,
        "VoiceSessionLeaseService",
        FakeVoiceSessionLeaseService,
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


def test_voice_websocket_emits_structured_lifecycle_logs(
    monkeypatch,
):
    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)

    import api.voice as voice_module

    events = []

    monkeypatch.setattr(
        voice_module,
        "log_voice_event",
        lambda **kwargs: events.append(dict(kwargs)),
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

        session_id = ready["session_id"]

        websocket.send_json(
            {
                "type": "turn.start",
                "turn_id": "turn-log-1",
            }
        )
        websocket.receive_json()

        websocket.send_bytes(b"audio")
        websocket.receive_json()

        websocket.send_json(
            {
                "type": "turn.commit",
                "turn_id": "turn-log-1",
            }
        )

        assert websocket.receive_json()["type"] == "transcript.final"
        assert websocket.receive_json()["type"] == "turn.committed"
        assert websocket.receive_json()["type"] == "assistant.response"

        websocket.close()

    assert [event["event"] for event in events] == [
        "session_started",
        "turn_started",
        "assistant_response_completed",
        "session_closed",
    ]

    assert events[0]["session_id"] == session_id
    assert events[1]["turn_id"] == "turn-log-1"
    assert events[2]["turn_id"] == "turn-log-1"
    assert events[2]["duration_ms"] >= 0
    assert events[3]["session_id"] == session_id

    for event in events:
        assert "user_id" not in event
        assert "message" not in event
        assert "transcript" not in event
        assert "access_token" not in event


def test_voice_websocket_enforces_turn_start_rate_limit(
    monkeypatch,
):
    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)

    import api.voice as voice_module

    FakeVoiceRateLimitService.instances = []

    monkeypatch.setattr(
        voice_module,
        "RateLimitService",
        FakeVoiceRateLimitService,
    )
    monkeypatch.setattr(
        voice_module,
        "get_rate_limit_settings",
        lambda: SimpleNamespace(
            voice_rate_limit_enabled=True,
            voice_turn_start_requests_per_window=1,
            voice_turn_start_window_seconds=60,
        ),
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
                "turn_id": "turn-rate-1",
            }
        )

        started = websocket.receive_json()

        assert started["type"] == "turn.started"
        assert started["turn_id"] == "turn-rate-1"

        websocket.send_json(
            {
                "type": "turn.cancel",
                "turn_id": "turn-rate-1",
            }
        )

        cancelled = websocket.receive_json()

        assert cancelled == {
            "type": "turn.cancelled",
            "turn_id": "turn-rate-1",
        }

        websocket.send_json(
            {
                "type": "turn.start",
                "turn_id": "turn-rate-2",
            }
        )

        error = websocket.receive_json()

        assert error == {
            "type": "error",
            "code": "voice_rate_limit_exceeded",
            "message": "Voice turn rate limit exceeded.",
            "recoverable": True,
            "recovery_action": "retry_after_reset",
            "retry_after_seconds": 17,
        }

        websocket.send_json(
            {
                "type": "session.ping",
            }
        )

        pong = websocket.receive_json()

        assert pong["type"] == "session.pong"

    limiter = FakeVoiceRateLimitService.instances[0]

    assert limiter.calls == [
        {
            "principal_key": "user:voice-test-user",
            "scope": "voice:turn_start",
            "limit": 1,
            "window_seconds": 60,
        },
        {
            "principal_key": "user:voice-test-user",
            "scope": "voice:turn_start",
            "limit": 1,
            "window_seconds": 60,
        },
    ]

    assert FakeVoiceSTTOrchestrator.instances[0].turn_id == (
        "turn-rate-1"
    )




def test_voice_websocket_renews_session_lease_while_idle(
    monkeypatch,
):
    import api.voice as voice_module

    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)

    voice_settings = voice_module.get_voice_settings().model_copy(
        update={
            "voice_session_lease_heartbeat_interval_seconds": 0.01,
        }
    )
    monkeypatch.setattr(
        voice_module,
        "get_voice_settings",
        lambda: voice_settings,
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

        lease_service = (
            FakeVoiceSessionLeaseService.instances[-1]
        )

        assert lease_service.heartbeat_event.wait(
            timeout=1
        )
        assert lease_service.heartbeat_calls > 0

        websocket.send_json(
            {
                "type": "session.ping",
            }
        )

        pong = websocket.receive_json()
        assert pong["type"] == "session.pong"


def test_voice_websocket_closes_when_session_lease_heartbeat_expires(
    monkeypatch,
):
    import api.voice as voice_module

    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)

    voice_settings = voice_module.get_voice_settings().model_copy(
        update={
            "voice_session_lease_heartbeat_interval_seconds": 0.01,
        }
    )
    monkeypatch.setattr(
        voice_module,
        "get_voice_settings",
        lambda: voice_settings,
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

        lease_service = (
            FakeVoiceSessionLeaseService.instances[-1]
        )
        lease_service.heartbeat_result = False

        error = websocket.receive_json()

        assert error == {
            "type": "error",
            "code": "voice_session_lease_expired",
            "message": "Voice session lease expired.",
            "recoverable": True,
            "recovery_action": "reconnect",
        }


def test_voice_websocket_limits_one_active_session_per_user(
    monkeypatch,
):
    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)

    import api.voice as voice_module

    client = TestClient(
        _build_app()
    )

    with client.websocket_connect(
        "/voice/ws",
        headers={
            "Authorization": "Bearer test-token",
        },
    ) as first:
        first_ready = first.receive_json()

        assert first_ready["type"] == "session.ready"

        with client.websocket_connect(
            "/voice/ws",
            headers={
                "Authorization": "Bearer test-token",
            },
        ) as second:
            error = second.receive_json()

            assert error == {
                "type": "error",
                "code": "voice_session_limit_exceeded",
                "message": (
                    "A voice session is already active "
                    "for this user."
                ),
                "recoverable": True,
                "recovery_action": "retry_after_reset",
                "retry_after_seconds": 23,
            }

        first.send_json(
            {
                "type": "session.ping",
            }
        )

        pong = first.receive_json()

        assert pong["type"] == "session.pong"


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

        cancelled_response = websocket.receive_json()
        assert cancelled_response == {
            "type": "assistant.response.cancelled",
            "turn_id": "turn-1",
        }

        cancelled_audio = websocket.receive_json()
        assert cancelled_audio == {
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

        cancelled_response = websocket.receive_json()
        assert cancelled_response == {
            "type": "assistant.response.cancelled",
            "turn_id": "turn-1",
        }

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


def test_voice_websocket_auto_commits_on_utterance_end(
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
                "turn_id": "turn-auto-utterance-end",
            }
        )
        websocket.receive_json()

        FakeVoiceSTTOrchestrator.instances[0].emit_utterance_end = True
        websocket.send_bytes(
            b"input-audio"
        )

        seen_types = []
        assistant = None

        while assistant is None:
            message = websocket.receive()

            if message.get("bytes") is not None:
                continue

            payload = json.loads(message["text"])
            seen_types.append(payload["type"])

            if payload["type"] == "assistant.response":
                assistant = payload
                continue

            if payload["type"] == "error":
                raise AssertionError(
                    f"Unexpected voice error: {payload!r}"
                )

        assert "transcript.final" in seen_types
        assert "transcript.utterance_end" in seen_types
        assert "turn.committed" in seen_types
        assert assistant["turn_id"] == "turn-auto-utterance-end"
        assert assistant["response"] == "Sure, done."


def test_voice_websocket_recovers_after_midstream_stt_provider_failure(
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
                "turn_id": "turn-stt-failure",
            }
        )
        started = websocket.receive_json()

        assert started["type"] == "turn.started"
        assert started["turn_id"] == "turn-stt-failure"

        stt = FakeVoiceSTTOrchestrator.instances[0]
        stt.emit_error = True

        websocket.send_bytes(
            b"failure-audio"
        )

        seen_error = None
        while seen_error is None:
            message = websocket.receive_json()

            if message["type"] == "error":
                seen_error = message

        assert seen_error["code"] == "stt_error"
        assert seen_error["recoverable"] is True
        assert seen_error["recovery_action"] == "start_new_turn"

        websocket.send_json(
            {
                "type": "turn.start",
                "turn_id": "turn-stt-recovered",
            }
        )

        recovered = websocket.receive_json()

        assert recovered["type"] == "turn.started"
        assert recovered["turn_id"] == "turn-stt-recovered"

        stt.emit_error = False

        websocket.send_bytes(
            b"recovered-audio"
        )

        partial = websocket.receive_json()

        assert partial["type"] == "transcript.partial"
        assert partial["turn_id"] == "turn-stt-recovered"

        websocket.send_json(
            {
                "type": "turn.cancel",
                "turn_id": "turn-stt-recovered",
            }
        )

        cancelled = websocket.receive_json()

        assert cancelled == {
            "type": "turn.cancelled",
            "turn_id": "turn-stt-recovered",
        }


def test_voice_websocket_recovers_after_midstream_tts_provider_failure(
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
                "turn_id": "turn-tts-failure",
            }
        )
        websocket.receive_json()

        fake_tts = FakeVoiceTTSOrchestrator.instances[0]
        fake_tts.emit_error = True

        websocket.send_bytes(
            b"tts-failure-input"
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
        assert websocket.receive_json()["type"] == "assistant.audio.started"

        fake_tts = FakeVoiceTTSOrchestrator.instances[0]

        error_message = None
        while error_message is None:
            message = websocket.receive()

            if message.get("bytes") is not None:
                continue

            text_data = message.get("text")
            if text_data is None:
                continue

            payload = json.loads(text_data)

            if payload["type"] == "error":
                error_message = payload
                continue

            if payload["type"] == "assistant.response":
                continue

        assert error_message["code"] == "assistant_audio_failed"
        assert error_message["recoverable"] is True
        assert error_message["recovery_action"] == "start_new_turn"

        websocket.send_json(
            {
                "type": "turn.start",
                "turn_id": "turn-tts-recovered",
            }
        )

        recovered = websocket.receive_json()

        assert recovered["type"] == "turn.started"
        assert recovered["turn_id"] == "turn-tts-recovered"

        websocket.send_bytes(
            b"next-input"
        )

        partial = websocket.receive_json()

        assert partial["type"] == "transcript.partial"


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



def test_voice_websocket_records_performance_metrics(monkeypatch):
    voice_module = _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)
    _patch_fake_tts(monkeypatch)

    metrics = RecordingVoiceMetrics()
    monkeypatch.setattr(voice_module, "voice_metrics", metrics)

    client = TestClient(_build_app())

    with client.websocket_connect(
        "/voice/ws",
        headers={"Authorization": "Bearer test-token"},
    ) as websocket:
        websocket.receive_json()
        websocket.send_json({"type": "turn.start", "turn_id": "turn-metrics"})
        websocket.receive_json()
        websocket.send_bytes(b"input-audio")
        websocket.receive_json()
        websocket.send_json({"type": "turn.commit", "turn_id": "turn-metrics"})

        assert websocket.receive_json()["type"] == "transcript.final"
        assert websocket.receive_json()["type"] == "turn.committed"
        assert websocket.receive_json()["type"] == "assistant.audio.started"

        seen_response = False
        seen_audio_final = False
        while not (seen_response and seen_audio_final):
            message = websocket.receive()
            if message.get("bytes") is not None:
                continue
            payload = json.loads(message["text"])
            if payload["type"] == "assistant.response":
                seen_response = True
            if payload["type"] == "assistant.audio.final":
                seen_audio_final = True

    assert metrics.stt_finalization
    assert metrics.llm_first_delta
    assert metrics.tts_first_audio
    assert metrics.turn_response
    assert metrics.turn_total
    assert ("deepgram", "stream_started") in metrics.provider_events
    assert ("elevenlabs", "stream_started") in metrics.provider_events



def test_voice_websocket_exercises_real_stt_tts_orchestrators_end_to_end(
    monkeypatch,
):
    import api.voice as voice_module

    _patch_auth(monkeypatch)

    stt_adapter = E2EVoiceSTTAdapter()
    tts_adapter = E2EVoiceTTSAdapter()

    monkeypatch.setattr(
        voice_module,
        "_build_voice_stt_orchestrator",
        lambda settings: VoiceSTTOrchestrator(
            adapter=stt_adapter,
            settings=settings,
        ),
    )
    monkeypatch.setattr(
        voice_module,
        "_build_voice_tts_orchestrator",
        lambda settings: VoiceTTSOrchestrator(
            adapter=tts_adapter,
            settings=settings,
        ),
    )
    monkeypatch.setattr(
        voice_module,
        "get_tts_provider_settings",
        lambda: SimpleNamespace(
            elevenlabs_voice_id="voice/e2e",
        ),
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

        websocket.send_json(
            {
                "type": "turn.start",
                "turn_id": "turn-e2e-1",
                "audio_format": {
                    "encoding": "pcm_s16le",
                    "sample_rate_hz": 16_000,
                    "channels": 1,
                },
            }
        )

        started = websocket.receive_json()

        assert started["type"] == "turn.started"
        assert started["turn_id"] == "turn-e2e-1"
        assert started["stt_stream_id"] == "e2e-stt-stream-1"
        assert started["started_at"]

        websocket.send_bytes(b"input-audio")

        speech_started = websocket.receive_json()
        assert speech_started["type"] == "speech.started"

        partial = websocket.receive_json()
        assert partial["type"] == "transcript.partial"
        assert partial["text"] == "hello"

        websocket.send_json(
            {
                "type": "turn.commit",
                "turn_id": "turn-e2e-1",
            }
        )

        final = websocket.receive_json()
        assert final["type"] == "transcript.final"
        assert final["text"] == "hello world"

        committed = websocket.receive_json()
        assert committed["type"] == "turn.committed"
        assert committed["turn_id"] == "turn-e2e-1"
        assert committed["transcript"] == "hello world"

        audio_started = websocket.receive_json()
        assert audio_started == {
            "type": "assistant.audio.started",
            "stream_id": "e2e-tts-stream-1",
            "turn_id": "turn-e2e-1",
            "audio_format": {
                "encoding": "pcm_s16le",
                "sample_rate_hz": 16_000,
                "channels": 1,
            },
        }

        received_audio = []
        received_json = []

        while True:
            message = websocket.receive()

            if message.get("bytes") is not None:
                received_audio.append(
                    message["bytes"]
                )
                continue

            payload = json.loads(
                message["text"]
            )
            received_json.append(payload)

            if {
                item["type"]
                for item in received_json
            } >= {
                "assistant.response",
                "assistant.audio.final",
            }:
                break

        assert received_audio == [
            b"audio-1",
            b"audio-2",
        ]

        response_message = next(
            item
            for item in received_json
            if item["type"] == "assistant.response"
        )
        assert response_message["response"] == "Sure, done."

        final_audio_message = next(
            item
            for item in received_json
            if item["type"] == "assistant.audio.final"
        )
        assert final_audio_message["stream_id"] == "e2e-tts-stream-1"
        assert final_audio_message["turn_id"] == "turn-e2e-1"

    assert ready["session_id"]
    assert stt_adapter.requests[0].user_id == "voice-test-user"
    assert stt_adapter.requests[0].session_id == ready["session_id"]
    assert stt_adapter.requests[0].turn_id == "turn-e2e-1"
    assert stt_adapter.stream is not None
    assert stt_adapter.stream.audio_frames == [b"input-audio"]

    assert tts_adapter.requests[0].user_id == "voice-test-user"
    assert tts_adapter.requests[0].session_id == ready["session_id"]
    assert tts_adapter.requests[0].turn_id == "turn-e2e-1"
    assert tts_adapter.requests[0].voice == "voice/e2e"
    assert tts_adapter.stream is not None
    assert tts_adapter.stream.text_chunks == [
        "Sure, ",
        "done.",
    ]
