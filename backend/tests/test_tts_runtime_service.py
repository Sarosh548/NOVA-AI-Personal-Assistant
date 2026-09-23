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
from services.tts_runtime_service import (
    TTSRuntimeError,
    TTSRuntimeService,
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


def make_event(
    stream_id: str,
    turn_id: str,
    sequence: int,
    *,
    type: str = "audio",
    audio: bytes = b"audio",
) -> TTSAudioEvent:
    return TTSAudioEvent(
        stream_id=stream_id,
        turn_id=turn_id,
        sequence=sequence,
        type=type,
        audio=audio,
        created_at=datetime.now(timezone.utc),
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
        self._event_ready = asyncio.Event()

    @property
    def stream_id(self) -> str:
        return self._stream_id

    @property
    def turn_id(self) -> str:
        return self._turn_id

    async def send_text(self, text: str) -> None:
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
        voice_tts_audio_chunk_max_bytes=1_024,
        voice_event_queue_enqueue_timeout_seconds=2.0,
    )


@pytest.mark.asyncio
async def test_runtime_starts_and_relays_ordered_events(
    settings: VoiceSettings,
) -> None:
    stream = FakeTTSStream(
        events=[
            make_event("stream-1", "turn-1", 1),
            make_event("stream-1", "turn-1", 2),
        ]
    )
    adapter = FakeTTSAdapter(stream)
    runtime = TTSRuntimeService(
        adapter,
        settings,
    )

    stream_id = await runtime.start_turn(
        make_request()
    )
    assert stream_id == "stream-1"

    await runtime.send_text(
        session_id="session-1",
        turn_id="turn-1",
        text="Hello",
    )

    events = [
        event
        async for event in runtime.events(
            session_id="session-1",
            turn_id="turn-1",
        )
    ]

    assert [event.sequence for event in events] == [1, 2]
    assert stream.sent_text == ["Hello"]

    await runtime.close_session("session-1")
    assert stream.closed is True


@pytest.mark.asyncio
async def test_runtime_finish_marks_turn_and_calls_stream_finish(
    settings: VoiceSettings,
) -> None:
    stream = FakeTTSStream()
    runtime = TTSRuntimeService(
        FakeTTSAdapter(stream),
        settings,
    )

    await runtime.start_turn(
        make_request()
    )

    await runtime.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
    )

    assert stream.finished is True

    with pytest.raises(
        TTSRuntimeError,
        match="no longer accepting text",
    ):
        await runtime.send_text(
            session_id="session-1",
            turn_id="turn-1",
            text="later",
        )

    await runtime.close_session("session-1")


@pytest.mark.asyncio
async def test_runtime_rejects_second_active_turn_for_same_session(
    settings: VoiceSettings,
) -> None:
    stream = FakeTTSStream()
    runtime = TTSRuntimeService(
        FakeTTSAdapter(stream),
        settings,
    )

    await runtime.start_turn(
        make_request()
    )

    with pytest.raises(
        TTSRuntimeError,
        match="already active",
    ):
        await runtime.start_turn(
            make_request(
                turn_id="turn-2"
            )
        )

    await runtime.cancel_turn(
        session_id="session-1",
        turn_id="turn-1",
    )


@pytest.mark.asyncio
async def test_runtime_rejects_wrong_stream_turn_id(
    settings: VoiceSettings,
) -> None:
    stream = FakeTTSStream(
        turn_id="different-turn"
    )
    runtime = TTSRuntimeService(
        FakeTTSAdapter(stream),
        settings,
    )

    with pytest.raises(
        TTSRuntimeError,
        match="different turn",
    ):
        await runtime.start_turn(
            make_request()
        )

    assert stream.closed is True


@pytest.mark.asyncio
async def test_runtime_rejects_invalid_event_sequence(
    settings: VoiceSettings,
) -> None:
    stream = FakeTTSStream(
        events=[
            make_event("stream-1", "turn-1", 2),
            make_event("stream-1", "turn-1", 1),
        ]
    )
    runtime = TTSRuntimeService(
        FakeTTSAdapter(stream),
        settings,
    )

    await runtime.start_turn(
        make_request()
    )

    with pytest.raises(
        TTSRuntimeError,
        match="strictly increasing",
    ):
        async for _event in runtime.events(
            session_id="session-1",
            turn_id="turn-1",
        ):
            pass


@pytest.mark.asyncio
async def test_runtime_event_queue_backpressure_fails_fast_and_cleans_up() -> None:
    stream = FakeTTSStream(
        events=[
            make_event("stream-1", "turn-1", 1),
            make_event("stream-1", "turn-1", 2),
        ]
    )
    runtime = TTSRuntimeService(
        FakeTTSAdapter(stream),
        VoiceSettings(
            voice_tts_event_queue_max_items=1,
            voice_tts_audio_chunk_max_bytes=1_024,
            voice_event_queue_enqueue_timeout_seconds=0.01,
        ),
    )

    await runtime.start_turn(
        make_request()
    )

    await asyncio.sleep(0.03)

    with pytest.raises(
        TTSRuntimeError,
        match="backpressure deadline",
    ):
        async for _event in runtime.events(
            session_id="session-1",
            turn_id="turn-1",
        ):
            pass

    assert stream.cancelled is True
    assert stream.closed is True
    assert runtime._turns == {}


@pytest.mark.asyncio
async def test_runtime_rejects_duplicate_final_event(
    settings: VoiceSettings,
) -> None:
    stream = FakeTTSStream(
        events=[
            make_event(
                "stream-1",
                "turn-1",
                1,
                type="final",
                audio=b"",
            ),
            make_event(
                "stream-1",
                "turn-1",
                2,
                type="final",
                audio=b"",
            ),
        ]
    )
    runtime = TTSRuntimeService(
        FakeTTSAdapter(stream),
        settings,
    )

    await runtime.start_turn(
        make_request()
    )

    with pytest.raises(
        TTSRuntimeError,
        match="more than once",
    ):
        async for _event in runtime.events(
            session_id="session-1",
            turn_id="turn-1",
        ):
            pass


@pytest.mark.asyncio
async def test_runtime_rejects_oversized_audio_chunk(
    settings: VoiceSettings,
) -> None:
    stream = FakeTTSStream(
        events=[
            make_event(
                "stream-1",
                "turn-1",
                1,
                audio=b"x" * 1_025,
            )
        ]
    )
    runtime = TTSRuntimeService(
        FakeTTSAdapter(stream),
        settings,
    )

    await runtime.start_turn(
        make_request()
    )

    with pytest.raises(
        TTSRuntimeError,
        match="audio chunk exceeds",
    ):
        async for _event in runtime.events(
            session_id="session-1",
            turn_id="turn-1",
        ):
            pass


@pytest.mark.asyncio
async def test_runtime_cancel_discards_active_turn(
    settings: VoiceSettings,
) -> None:
    stream = FakeTTSStream()
    runtime = TTSRuntimeService(
        FakeTTSAdapter(stream),
        settings,
    )

    await runtime.start_turn(
        make_request()
    )

    await runtime.cancel_turn(
        session_id="session-1",
        turn_id="turn-1",
    )

    assert stream.cancelled is True
    assert stream.closed is True

    with pytest.raises(
        TTSRuntimeError,
        match="No active TTS turn",
    ):
        await runtime.events(
            session_id="session-1",
            turn_id="turn-1",
        ).__anext__()


@pytest.mark.asyncio
async def test_runtime_rejects_second_event_consumer(
    settings: VoiceSettings,
) -> None:
    stream = FakeTTSStream(
        events=[
            make_event(
                "stream-1",
                "turn-1",
                1,
                type="final",
                audio=b"",
            )
        ]
    )
    runtime = TTSRuntimeService(
        FakeTTSAdapter(stream),
        settings,
    )

    await runtime.start_turn(
        make_request()
    )

    first = runtime.events(
        session_id="session-1",
        turn_id="turn-1",
    )

    await first.__anext__()

    second = runtime.events(
        session_id="session-1",
        turn_id="turn-1",
    )

    with pytest.raises(
        TTSRuntimeError,
        match="Only one audio event consumer",
    ):
        await second.__anext__()

    await first.aclose()


@pytest.mark.asyncio
async def test_runtime_rejects_oversized_text(
    settings: VoiceSettings,
) -> None:
    stream = FakeTTSStream()
    runtime = TTSRuntimeService(
        FakeTTSAdapter(stream),
        settings,
    )

    await runtime.start_turn(
        make_request()
    )

    with pytest.raises(
        TTSRuntimeError,
        match="exceeds the configured size limit",
    ):
        await runtime.send_text(
            session_id="session-1",
            turn_id="turn-1",
            text="x" * 16_385,
        )

    await runtime.cancel_turn(
        session_id="session-1",
        turn_id="turn-1",
    )
