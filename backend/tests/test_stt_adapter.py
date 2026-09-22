from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from services.stt_adapter import (
    STTAdapter,
    STTAudioFormat,
    STTStream,
    STTStreamClosedError,
    STTStreamNotActiveError,
    STTStreamRequest,
    STTTranscriptEvent,
    utc_now,
)


class FakeSTTStream(STTStream):
    def __init__(self, stream_id: str, turn_id: str):
        self._stream_id = stream_id
        self._turn_id = turn_id
        self.audio_frames: list[bytes] = []
        self.finished = False
        self.cancelled = False
        self.closed = False
        self._events_queue: asyncio.Queue[
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
        if self.closed:
            raise STTStreamClosedError(
                "STT stream is closed."
            )

        if self.finished or self.cancelled:
            raise STTStreamNotActiveError(
                "STT stream is no longer accepting audio."
            )

        if not frame:
            raise ValueError(
                "Audio frame cannot be empty."
            )

        self.audio_frames.append(frame)

    async def events(
        self,
    ) -> AsyncIterator[STTTranscriptEvent]:
        while True:
            event = await self._events_queue.get()

            if event is None:
                return

            yield event

    async def finish(self) -> None:
        if self.closed:
            raise STTStreamClosedError(
                "STT stream is closed."
            )

        if self.cancelled:
            raise STTStreamNotActiveError(
                "Cancelled STT stream cannot be finished."
            )

        if not self.finished:
            self.finished = True

    async def cancel(self) -> None:
        if self.closed:
            return

        if not self.cancelled:
            self.cancelled = True

        await self._events_queue.put(None)

    async def close(self) -> None:
        if self.closed:
            return

        self.closed = True
        await self._events_queue.put(None)

    async def emit(
        self,
        event: STTTranscriptEvent,
    ) -> None:
        if self.closed or self.cancelled:
            raise STTStreamNotActiveError(
                "Cannot emit after stream cancellation or closure."
            )

        await self._events_queue.put(event)


class FakeSTTAdapter(STTAdapter):
    def __init__(self):
        self.requests: list[STTStreamRequest] = []
        self.streams: list[FakeSTTStream] = []

    async def start_stream(
        self,
        request: STTStreamRequest,
    ) -> STTStream:
        self.requests.append(request)

        stream = FakeSTTStream(
            stream_id=f"stream-{len(self.streams) + 1}",
            turn_id=request.turn_id,
        )
        self.streams.append(stream)

        return stream


def test_audio_format_normalizes_encoding_and_validates_bounds():
    audio_format = STTAudioFormat(
        encoding=" PCM_S16LE ",
        sample_rate_hz=16_000,
        channels=1,
    )

    assert audio_format.encoding == "pcm_s16le"
    assert audio_format.sample_rate_hz == 16_000
    assert audio_format.channels == 1

    with pytest.raises(
        ValueError,
        match="sample_rate_hz",
    ):
        STTAudioFormat(
            encoding="pcm_s16le",
            sample_rate_hz=7_999,
            channels=1,
        )

    with pytest.raises(
        ValueError,
        match="channels",
    ):
        STTAudioFormat(
            encoding="pcm_s16le",
            sample_rate_hz=16_000,
            channels=0,
        )


def test_stream_request_binds_user_session_turn_and_audio_format():
    request = STTStreamRequest(
        user_id=" user-1 ",
        session_id=" session-1 ",
        turn_id=" turn-1 ",
        audio_format=STTAudioFormat(
            encoding="opus",
            sample_rate_hz=48_000,
            channels=1,
        ),
    )

    assert request.user_id == "user-1"
    assert request.session_id == "session-1"
    assert request.turn_id == "turn-1"
    assert request.audio_format.encoding == "opus"


def test_transcript_event_supports_ordered_partial_and_final_updates():
    created_at = utc_now()

    partial = STTTranscriptEvent(
        stream_id="stream-1",
        turn_id="turn-1",
        sequence=1,
        type="partial",
        text="hello wor",
        created_at=created_at,
    )

    final = STTTranscriptEvent(
        stream_id="stream-1",
        turn_id="turn-1",
        sequence=2,
        type="final",
        text="hello world",
        created_at=created_at,
    )

    assert partial.type == "partial"
    assert partial.sequence < final.sequence
    assert final.type == "final"
    assert final.text == "hello world"
    assert final.created_at.tzinfo is not None


def test_transcript_event_rejects_invalid_or_empty_text():
    with pytest.raises(
        ValueError,
        match="text cannot be empty",
    ):
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=1,
            type="partial",
            text="   ",
            created_at=utc_now(),
        )

    with pytest.raises(
        ValueError,
        match="sequence",
    ):
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=-1,
            type="partial",
            text="hello",
            created_at=utc_now(),
        )


@pytest.mark.asyncio
async def test_adapter_starts_stream_with_exact_turn_contract():
    adapter = FakeSTTAdapter()

    request = STTStreamRequest(
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        audio_format=STTAudioFormat(
            encoding="pcm_s16le",
            sample_rate_hz=16_000,
            channels=1,
        ),
    )

    stream = await adapter.start_stream(
        request
    )

    assert stream.stream_id == "stream-1"
    assert stream.turn_id == "turn-1"
    assert adapter.requests == [request]


@pytest.mark.asyncio
async def test_stream_delivers_partial_then_final_transcript_events():
    stream = FakeSTTStream(
        stream_id="stream-1",
        turn_id="turn-1",
    )

    await stream.send_audio(
        b"audio-1"
    )
    await stream.send_audio(
        b"audio-2"
    )

    await stream.emit(
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=1,
            type="partial",
            text="set a",
            created_at=utc_now(),
        )
    )
    await stream.emit(
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=2,
            type="final",
            text="set a reminder",
            created_at=utc_now(),
        )
    )

    await stream.finish()
    await stream.close()

    assert stream.audio_frames == [
        b"audio-1",
        b"audio-2",
    ]
    assert stream.finished is True


@pytest.mark.asyncio
async def test_stream_events_are_ordered_by_provider_sequence():
    stream = FakeSTTStream(
        stream_id="stream-1",
        turn_id="turn-1",
    )

    events = [
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=1,
            type="partial",
            text="remind",
            created_at=utc_now(),
        ),
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=2,
            type="partial",
            text="remind me",
            created_at=utc_now(),
        ),
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=3,
            type="final",
            text="remind me tomorrow",
            created_at=utc_now(),
        ),
    ]

    for event in events:
        await stream.emit(event)

    received: list[STTTranscriptEvent] = []

    async def consume() -> None:
        async for event in stream.events():
            received.append(event)

            if event.type == "final":
                return

    consumer = asyncio.create_task(
        consume()
    )

    await asyncio.wait_for(
        consumer,
        timeout=1,
    )

    assert [
        event.sequence
        for event in received
    ] == [1, 2, 3]

    assert received[-1].type == "final"


@pytest.mark.asyncio
async def test_cancel_stops_stream_and_prevents_future_audio():
    stream = FakeSTTStream(
        stream_id="stream-1",
        turn_id="turn-1",
    )

    await stream.send_audio(
        b"audio"
    )

    await stream.cancel()

    assert stream.cancelled is True

    with pytest.raises(
        STTStreamNotActiveError
    ):
        await stream.send_audio(
            b"late-audio"
        )


@pytest.mark.asyncio
async def test_close_is_idempotent_and_prevents_reuse():
    stream = FakeSTTStream(
        stream_id="stream-1",
        turn_id="turn-1",
    )

    await stream.close()
    await stream.close()

    assert stream.closed is True

    with pytest.raises(
        STTStreamClosedError
    ):
        await stream.send_audio(
            b"audio"
        )
