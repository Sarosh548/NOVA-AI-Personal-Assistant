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
from services.voice_stt_orchestrator import (
    VoiceSTTOrchestrator,
    VoiceSTTOrchestratorError,
)


class FakeStream(STTStream):
    def __init__(self, turn_id: str):
        self._stream_id = "stream-1"
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

    async def send_audio(self, frame: bytes) -> None:
        if self.finished or self.cancelled or self.closed:
            raise RuntimeError("inactive")
        self.audio_frames.append(frame)

    async def events(self) -> AsyncIterator[STTTranscriptEvent]:
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event

    async def finish(self) -> None:
        self.finished = True

    async def cancel(self) -> None:
        self.cancelled = True
        await self._events.put(None)

    async def close(self) -> None:
        self.closed = True
        await self._events.put(None)

    async def emit(self, event: STTTranscriptEvent) -> None:
        await self._events.put(event)


class FakeAdapter(STTAdapter):
    def __init__(self):
        self.stream: FakeStream | None = None
        self.requests: list[STTStreamRequest] = []

    async def start_stream(
        self,
        request: STTStreamRequest,
    ) -> STTStream:
        self.requests.append(request)
        self.stream = FakeStream(request.turn_id)
        return self.stream


def _settings(**overrides) -> VoiceSettings:
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
        "voice_stt_finalization_timeout_seconds": 1.0,
    }
    values.update(overrides)
    return VoiceSettings(**values)


def _format() -> STTAudioFormat:
    return STTAudioFormat(
        encoding="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
    )


async def _start(service: VoiceSTTOrchestrator) -> None:
    await service.start_turn(
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        audio_format=_format(),
    )


@pytest.mark.asyncio
async def test_start_binds_identity_and_format():
    adapter = FakeAdapter()
    service = VoiceSTTOrchestrator(
        adapter=adapter,
        settings=_settings(),
    )

    stream_id = await service.start_turn(
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        audio_format=_format(),
    )

    assert stream_id == "stream-1"
    assert adapter.requests[0].user_id == "user-1"
    assert adapter.requests[0].session_id == "session-1"
    assert adapter.requests[0].turn_id == "turn-1"
    assert adapter.requests[0].audio_format == _format()

    await service.cancel_turn()


@pytest.mark.asyncio
async def test_audio_is_forwarded():
    adapter = FakeAdapter()
    service = VoiceSTTOrchestrator(
        adapter=adapter,
        settings=_settings(),
    )

    await _start(service)
    await service.send_audio(b"audio")

    assert adapter.stream is not None
    assert adapter.stream.audio_frames == [b"audio"]

    await service.cancel_turn()


@pytest.mark.asyncio
async def test_partial_and_final_events_are_relayed_as_protocol_events():
    adapter = FakeAdapter()
    service = VoiceSTTOrchestrator(
        adapter=adapter,
        settings=_settings(),
    )

    await _start(service)
    consumer = service.events()

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
            is_end_of_speech=True,
            created_at=utc_now(),
        )
    )

    first = await asyncio.wait_for(
        anext(consumer),
        timeout=1,
    )
    second = await asyncio.wait_for(
        anext(consumer),
        timeout=1,
    )

    assert first["type"] == "transcript.partial"
    assert second["type"] == "transcript.final"
    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert first["is_end_of_speech"] is False
    assert second["is_end_of_speech"] is True

    await consumer.aclose()


@pytest.mark.asyncio
async def test_end_of_speech_assembles_multiple_final_segments():
    adapter = FakeAdapter()
    service = VoiceSTTOrchestrator(
        adapter=adapter,
        settings=_settings(),
    )

    await _start(service)

    consumer = service.events()

    assert adapter.stream is not None
    await adapter.stream.emit(
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=1,
            type="final",
            text="yeah so",
            created_at=utc_now(),
        )
    )
    assert (
        await anext(consumer)
    )["text"] == "yeah so"

    await adapter.stream.emit(
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=2,
            type="final",
            text="my credit card number is two two three three",
            is_end_of_speech=True,
            created_at=utc_now(),
        )
    )
    assert (
        await anext(consumer)
    )["text"] == (
        "my credit card number is two two three three"
    )

    final = await service.finish_turn()

    assert final.type == "final"
    assert final.text == (
        "yeah so my credit card number is two two three three"
    )
    assert final.is_end_of_speech is True
    assert adapter.stream.closed is True

    await consumer.aclose()


@pytest.mark.asyncio
async def test_manual_finish_waits_for_post_finalize_final_segment():
    adapter = FakeAdapter()
    service = VoiceSTTOrchestrator(
        adapter=adapter,
        settings=_settings(),
    )

    await _start(service)

    consumer = service.events()

    assert adapter.stream is not None
    await adapter.stream.emit(
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=1,
            type="final",
            text="hello",
            created_at=utc_now(),
        )
    )
    assert (
        await anext(consumer)
    )["text"] == "hello"

    finish_task = asyncio.create_task(
        service.finish_turn()
    )
    await asyncio.sleep(0)

    assert adapter.stream.finished is True
    assert not finish_task.done()

    await adapter.stream.emit(
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=2,
            type="final",
            text="world",
            created_at=utc_now(),
        )
    )

    final = await asyncio.wait_for(
        finish_task,
        timeout=1,
    )

    assert final.type == "final"
    assert final.text == "hello world"
    assert final.is_end_of_speech is True
    assert adapter.stream.closed is True

    await consumer.aclose()


@pytest.mark.asyncio
async def test_finish_waits_for_final_and_releases_provider():
    adapter = FakeAdapter()
    service = VoiceSTTOrchestrator(
        adapter=adapter,
        settings=_settings(),
    )

    await _start(service)

    finish_task = asyncio.create_task(
        service.finish_turn()
    )
    await asyncio.sleep(0)

    assert adapter.stream is not None
    assert adapter.stream.finished is True

    await adapter.stream.emit(
        STTTranscriptEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=1,
            type="final",
            text="hello",
            created_at=utc_now(),
        )
    )

    final = await asyncio.wait_for(
        finish_task,
        timeout=1,
    )

    assert final.type == "final"
    assert final.text == "hello"
    assert adapter.stream.closed is True


@pytest.mark.asyncio
async def test_finish_timeout_cancels_provider():
    adapter = FakeAdapter()
    service = VoiceSTTOrchestrator(
        adapter=adapter,
        settings=_settings(
            voice_stt_finalization_timeout_seconds=0.01
        ),
    )

    await _start(service)

    with pytest.raises(
        VoiceSTTOrchestratorError,
        match="final transcript",
    ):
        await service.finish_turn()

    assert adapter.stream is not None
    assert adapter.stream.cancelled is True
    assert adapter.stream.closed is True


@pytest.mark.asyncio
async def test_cancel_releases_provider():
    adapter = FakeAdapter()
    service = VoiceSTTOrchestrator(
        adapter=adapter,
        settings=_settings(),
    )

    await _start(service)
    await service.cancel_turn()

    assert adapter.stream is not None
    assert adapter.stream.cancelled is True
    assert adapter.stream.closed is True


@pytest.mark.asyncio
async def test_second_event_consumer_is_rejected():
    adapter = FakeAdapter()
    service = VoiceSTTOrchestrator(
        adapter=adapter,
        settings=_settings(),
    )

    await _start(service)

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

    consumer_one = service.events()
    assert (
        await anext(consumer_one)
    )["type"] == "transcript.partial"

    consumer_two = service.events()
    with pytest.raises(
        VoiceSTTOrchestratorError,
        match="one voice STT event consumer",
    ):
        await consumer_two.__anext__()

    await consumer_one.aclose()


@pytest.mark.asyncio
async def test_close_session_releases_provider():
    adapter = FakeAdapter()
    service = VoiceSTTOrchestrator(
        adapter=adapter,
        settings=_settings(),
    )

    await _start(service)
    await service.close_session()

    assert adapter.stream is not None
    assert adapter.stream.cancelled is True
    assert adapter.stream.closed is True
