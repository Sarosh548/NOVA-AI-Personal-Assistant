from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from config import VoiceSettings
from services.tts_adapter import (
    TTSAudioEvent,
    TTSAudioFormat,
    TTSAdapter,
    TTSStream,
    TTSStreamRequest,
)
from services.voice_tts_orchestrator import (
    VoiceTTSOrchestrator,
    VoiceTTSOrchestratorError,
)


def make_request(
    *,
    session_id: str = "session-1",
    turn_id: str = "turn-1",
) -> TTSStreamRequest:
    return TTSStreamRequest(
        user_id="user-1",
        session_id=session_id,
        turn_id=turn_id,
        voice="voice-1",
        audio_format=TTSAudioFormat(
            encoding="pcm_s16le",
            sample_rate_hz=16_000,
            channels=1,
        ),
    )


class FakeTTSStream(TTSStream):
    def __init__(
        self,
        *,
        stream_id: str = "stream-1",
        turn_id: str = "turn-1",
        events: list[TTSAudioEvent] | None = None,
    ) -> None:
        self._stream_id = stream_id
        self._turn_id = turn_id
        self._events = events or []
        self.sent_text: list[str] = []
        self.finished = False
        self.cancelled = False
        self.closed = False

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
        self.sent_text.append(text)

    async def events(self):
        for event in self._events:
            await asyncio.sleep(0)
            yield event

    async def finish(self) -> None:
        self.finished = True

    async def cancel(self) -> None:
        self.cancelled = True

    async def close(self) -> None:
        self.closed = True


class FakeTTSAdapter(TTSAdapter):
    def __init__(
        self,
        stream: FakeTTSStream,
    ) -> None:
        self.stream = stream
        self.requests: list[TTSStreamRequest] = []

    async def start_stream(
        self,
        request: TTSStreamRequest,
    ) -> TTSStream:
        self.requests.append(request)
        return self.stream


@pytest.fixture
def settings() -> VoiceSettings:
    return VoiceSettings(
        voice_tts_event_queue_max_items=4,
        voice_tts_audio_chunk_max_bytes=64,
    )


@pytest.mark.asyncio
async def test_orchestrator_streams_text_and_events(
    settings: VoiceSettings,
) -> None:
    stream = FakeTTSStream(
        events=[
            TTSAudioEvent(
                stream_id="stream-1",
                turn_id="turn-1",
                sequence=1,
                type="audio",
                audio=b"hello",
                created_at=datetime.now(timezone.utc),
            ),
            TTSAudioEvent(
                stream_id="stream-1",
                turn_id="turn-1",
                sequence=2,
                type="final",
                audio=b"",
                created_at=datetime.now(timezone.utc),
            ),
        ]
    )
    adapter = FakeTTSAdapter(stream)
    orchestrator = VoiceTTSOrchestrator(
        adapter,
        settings,
    )

    stream_id = await orchestrator.start_turn(
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        voice="voice-1",
        audio_format=make_request().audio_format,
    )

    assert stream_id == "stream-1"

    await orchestrator.send_text(
        "Hello NOVA"
    )
    await orchestrator.finish_turn()

    events = [
        event
        async for event in orchestrator.events()
    ]

    assert [event.type for event in events] == [
        "audio",
        "final",
    ]
    assert stream.sent_text == ["Hello NOVA"]
    assert stream.finished is True
    assert adapter.requests[0].voice == "voice-1"


@pytest.mark.asyncio
async def test_orchestrator_allows_only_one_active_turn(
    settings: VoiceSettings,
) -> None:
    stream = FakeTTSStream()
    orchestrator = VoiceTTSOrchestrator(
        FakeTTSAdapter(stream),
        settings,
    )

    await orchestrator.start_turn(
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        voice="voice-1",
        audio_format=make_request().audio_format,
    )

    with pytest.raises(
        VoiceTTSOrchestratorError,
        match="already active",
    ):
        await orchestrator.start_turn(
            user_id="user-1",
            session_id="session-1",
            turn_id="turn-2",
            voice="voice-1",
            audio_format=make_request(
                turn_id="turn-2"
            ).audio_format,
        )

    await orchestrator.cancel_turn()
    assert stream.cancelled is True
    assert stream.closed is True


@pytest.mark.asyncio
async def test_orchestrator_cancel_cleans_up_active_stream(
    settings: VoiceSettings,
) -> None:
    stream = FakeTTSStream()
    orchestrator = VoiceTTSOrchestrator(
        FakeTTSAdapter(stream),
        settings,
    )

    await orchestrator.start_turn(
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        voice="voice-1",
        audio_format=make_request().audio_format,
    )

    await orchestrator.cancel_turn()

    assert stream.cancelled is True
    assert stream.closed is True

    with pytest.raises(
        VoiceTTSOrchestratorError,
        match="No active voice TTS turn",
    ):
        await orchestrator.events().__anext__()


@pytest.mark.asyncio
async def test_orchestrator_rejects_second_event_consumer(
    settings: VoiceSettings,
) -> None:
    stream = FakeTTSStream(
        events=[
            TTSAudioEvent(
                stream_id="stream-1",
                turn_id="turn-1",
                sequence=1,
                type="final",
                audio=b"",
                created_at=datetime.now(timezone.utc),
            )
        ]
    )
    orchestrator = VoiceTTSOrchestrator(
        FakeTTSAdapter(stream),
        settings,
    )

    await orchestrator.start_turn(
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        voice="voice-1",
        audio_format=make_request().audio_format,
    )

    first = orchestrator.events()
    await first.__anext__()

    second = orchestrator.events()

    with pytest.raises(
        VoiceTTSOrchestratorError,
        match="Only one voice TTS event consumer",
    ):
        await second.__anext__()

    await first.aclose()


@pytest.mark.asyncio
async def test_orchestrator_close_session_is_idempotent(
    settings: VoiceSettings,
) -> None:
    stream = FakeTTSStream()
    orchestrator = VoiceTTSOrchestrator(
        FakeTTSAdapter(stream),
        settings,
    )

    await orchestrator.start_turn(
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        voice="voice-1",
        audio_format=make_request().audio_format,
    )

    await orchestrator.close_session()
    await orchestrator.close_session()

    assert stream.closed is True
