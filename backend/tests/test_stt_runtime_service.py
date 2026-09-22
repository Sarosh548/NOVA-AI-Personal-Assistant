from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from config import VoiceSettings
from services.stt_adapter import (
    STTAdapter,
    STTAudioFormat,
    STTStream,
    STTStreamRequest,
    STTTranscriptEvent,
    utc_now,
)
from services.stt_runtime_service import (
    STTRuntimeError,
    STTRuntimeService,
)


class RuntimeFakeStream(STTStream):
    def __init__(
        self,
        stream_id: str,
        turn_id: str,
    ):
        self._stream_id = stream_id
        self._turn_id = turn_id
        self.audio_frames: list[bytes] = []
        self.finished = False
        self.cancelled = False
        self.closed = False
        self._events: asyncio.Queue[
            STTTranscriptEvent | None
        ] = asyncio.Queue()

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
        if self.cancelled or self.closed:
            raise RuntimeError(
                "stream inactive"
            )
        self.audio_frames.append(frame)

    async def events(
        self,
    ) -> AsyncIterator[STTTranscriptEvent]:
        while True:
            event = await self._events.get()

            if event is None:
                return

            yield event

    async def finish(self) -> None:
        if self.cancelled or self.closed:
            raise RuntimeError(
                "stream inactive"
            )

        self.finished = True

    async def cancel(self) -> None:
        self.cancelled = True
        await self._events.put(None)

    async def close(self) -> None:
        self.closed = True

    async def emit(
        self,
        event: STTTranscriptEvent,
    ) -> None:
        if self.cancelled or self.closed:
            raise RuntimeError(
                "stream inactive"
            )

        await self._events.put(event)

    async def end_events(self) -> None:
        await self._events.put(None)


class RuntimeFakeAdapter(STTAdapter):
    def __init__(
        self,
        stream: RuntimeFakeStream | None = None,
    ):
        self.stream = stream
        self.requests: list[STTStreamRequest] = []

    async def start_stream(
        self,
        request: STTStreamRequest,
    ) -> STTStream:
        self.requests.append(request)

        if self.stream is None:
            self.stream = RuntimeFakeStream(
                stream_id="stream-1",
                turn_id=request.turn_id,
            )

        return self.stream


def _settings(
    **overrides,
) -> VoiceSettings:
    values = {
        "voice_control_message_max_bytes": 1024,
        "voice_audio_frame_max_bytes": 1024,
        "voice_turn_audio_max_bytes": 65536,
        "voice_turn_max_frames": 4,
        "voice_session_idle_timeout_seconds": 60,
        "voice_authentication_timeout_seconds": 10,
        "voice_session_max_duration_seconds": 1800,
        "voice_turn_max_duration_seconds": 30,
        "voice_stt_event_queue_max_items": 4,
    }
    values.update(overrides)
    return VoiceSettings(**values)


def _request(
    turn_id: str = "turn-1",
) -> STTStreamRequest:
    return STTStreamRequest(
        user_id="user-1",
        session_id="session-1",
        turn_id=turn_id,
        audio_format=STTAudioFormat(
            encoding="pcm_s16le",
            sample_rate_hz=16_000,
            channels=1,
        ),
    )


@pytest.mark.asyncio
async def test_start_turn_creates_stream_with_exact_request():
    adapter = RuntimeFakeAdapter()
    runtime = STTRuntimeService(
        adapter=adapter,
        settings=_settings(),
    )

    stream_id = await runtime.start_turn(
        _request()
    )

    assert stream_id == "stream-1"
    assert adapter.requests == [
        _request()
    ]

    await runtime.close_session(
        "session-1"
    )


@pytest.mark.asyncio
async def test_only_one_turn_can_be_active_per_session():
    adapter = RuntimeFakeAdapter()
    runtime = STTRuntimeService(
        adapter=adapter,
        settings=_settings(),
    )

    await runtime.start_turn(
        _request(
            "turn-1"
        )
    )

    with pytest.raises(
        STTRuntimeError,
        match="already active",
    ):
        await runtime.start_turn(
            _request(
                "turn-2"
            )
        )

    await runtime.close_session(
        "session-1"
    )


@pytest.mark.asyncio
async def test_audio_is_forwarded_to_provider_stream():
    adapter = RuntimeFakeAdapter()
    runtime = STTRuntimeService(
        adapter=adapter,
        settings=_settings(),
    )

    await runtime.start_turn(
        _request()
    )

    await runtime.send_audio(
        session_id="session-1",
        turn_id="turn-1",
        frame=b"audio",
    )

    assert adapter.stream is not None
    assert adapter.stream.audio_frames == [
        b"audio"
    ]

    await runtime.cancel_turn(
        session_id="session-1",
        turn_id="turn-1",
    )


@pytest.mark.asyncio
async def test_audio_frame_bounds_are_enforced_before_provider_call():
    adapter = RuntimeFakeAdapter()
    runtime = STTRuntimeService(
        adapter=adapter,
        settings=_settings(
            voice_audio_frame_max_bytes=1024
        ),
    )

    await runtime.start_turn(
        _request()
    )

    with pytest.raises(
        STTRuntimeError,
        match="size limit",
    ):
        await runtime.send_audio(
            session_id="session-1",
            turn_id="turn-1",
            frame=b"x" * 1025,
        )

    assert adapter.stream is not None
    assert adapter.stream.audio_frames == []

    await runtime.cancel_turn(
        session_id="session-1",
        turn_id="turn-1",
    )


@pytest.mark.asyncio
async def test_partial_and_final_events_are_relayed_in_order():
    adapter = RuntimeFakeAdapter()
    runtime = STTRuntimeService(
        adapter=adapter,
        settings=_settings(),
    )

    await runtime.start_turn(
        _request()
    )

    assert adapter.stream is not None

    await adapter.stream.emit(
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=1,
            type="partial",
            text="set a",
            created_at=utc_now(),
        )
    )

    await adapter.stream.emit(
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=2,
            type="final",
            text="set a reminder",
            created_at=utc_now(),
        )
    )

    await adapter.stream.end_events()

    received: list[STTTranscriptEvent] = []

    async for event in runtime.events(
        session_id="session-1",
        turn_id="turn-1",
    ):
        received.append(event)

    assert [event.type for event in received] == [
        "partial",
        "final",
    ]
    assert [event.sequence for event in received] == [
        1,
        2,
    ]
    assert runtime._turns == {}


@pytest.mark.asyncio
async def test_out_of_order_events_fail_the_stream():
    adapter = RuntimeFakeAdapter()
    runtime = STTRuntimeService(
        adapter=adapter,
        settings=_settings(),
    )

    await runtime.start_turn(
        _request()
    )

    assert adapter.stream is not None

    await adapter.stream.emit(
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=2,
            type="partial",
            text="hello",
            created_at=utc_now(),
        )
    )

    await adapter.stream.emit(
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=1,
            type="final",
            text="hello world",
            created_at=utc_now(),
        )
    )

    await adapter.stream.end_events()

    with pytest.raises(
        STTRuntimeError,
        match="sequence",
    ):
        async for _event in runtime.events(
            session_id="session-1",
            turn_id="turn-1",
        ):
            pass


@pytest.mark.asyncio
async def test_mismatched_stream_identity_fails_safely():
    adapter = RuntimeFakeAdapter(
        stream=RuntimeFakeStream(
            stream_id="stream-foreign",
            turn_id="turn-1",
        )
    )
    runtime = STTRuntimeService(
        adapter=adapter,
        settings=_settings(),
    )

    await runtime.start_turn(
        _request()
    )

    assert adapter.stream is not None

    await adapter.stream.emit(
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=1,
            type="partial",
            text="hello",
            created_at=utc_now(),
        )
    )

    with pytest.raises(
        STTRuntimeError,
        match="stream id",
    ):
        async for _event in runtime.events(
            session_id="session-1",
            turn_id="turn-1",
        ):
            pass

    assert adapter.stream.cancelled is True
    assert adapter.stream.closed is True
    assert runtime._turns == {}


@pytest.mark.asyncio
async def test_cancel_stops_provider_and_discards_pending_events():
    adapter = RuntimeFakeAdapter()
    runtime = STTRuntimeService(
        adapter=adapter,
        settings=_settings(),
    )

    await runtime.start_turn(
        _request()
    )

    assert adapter.stream is not None

    await adapter.stream.emit(
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=1,
            type="partial",
            text="do",
            created_at=utc_now(),
        )
    )

    await runtime.cancel_turn(
        session_id="session-1",
        turn_id="turn-1",
    )

    assert adapter.stream.cancelled is True
    assert adapter.stream.closed is True
    assert runtime._turns == {}


@pytest.mark.asyncio
async def test_finish_prevents_late_audio():
    adapter = RuntimeFakeAdapter()
    runtime = STTRuntimeService(
        adapter=adapter,
        settings=_settings(),
    )

    await runtime.start_turn(
        _request()
    )

    await runtime.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
    )

    assert adapter.stream is not None
    assert adapter.stream.finished is True

    with pytest.raises(
        STTRuntimeError,
        match="no longer accepting",
    ):
        await runtime.send_audio(
            session_id="session-1",
            turn_id="turn-1",
            frame=b"late",
        )

    await runtime.cancel_turn(
        session_id="session-1",
        turn_id="turn-1",
    )


@pytest.mark.asyncio
async def test_only_one_event_consumer_is_allowed():
    adapter = RuntimeFakeAdapter()
    runtime = STTRuntimeService(
        adapter=adapter,
        settings=_settings(),
    )

    await runtime.start_turn(
        _request()
    )

    assert adapter.stream is not None

    await adapter.stream.emit(
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=1,
            type="partial",
            text="hello",
            created_at=utc_now(),
        )
    )

    consumer_one = runtime.events(
        session_id="session-1",
        turn_id="turn-1",
    )

    first = await consumer_one.__anext__()

    assert first is not None

    with pytest.raises(
        STTRuntimeError,
        match="one transcript event consumer",
    ):
        duplicate = runtime.events(
            session_id="session-1",
            turn_id="turn-1",
        )
        await duplicate.__anext__()

    await consumer_one.aclose()

    assert adapter.stream is not None
    assert adapter.stream.cancelled is True
