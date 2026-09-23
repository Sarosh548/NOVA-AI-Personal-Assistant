from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import pytest

from config import STTProviderSettings
from services.deepgram_stt_adapter import (
    DeepgramSTTAdapter,
    DeepgramSTTStream,
)
from services.stt_adapter import (
    STTAdapterError,
    STTAudioFormat,
    STTStreamClosedError,
    STTStreamNotActiveError,
    STTStreamRequest,
    STTTranscriptEvent,
    utc_now,
)


class FakeDeepgramWebSocket:
    def __init__(self):
        self.sent: list[bytes | str] = []
        self.incoming: asyncio.Queue[str | None] = asyncio.Queue()
        self.closed = False
        self.close_timeout = None
        self.id = "provider-stream-1"

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        message = await self.incoming.get()

        if message is None:
            raise StopAsyncIteration

        return message

    async def send(
        self,
        payload,
    ) -> None:
        self.sent.append(payload)

    async def close(
        self,
        **kwargs,
    ) -> None:
        self.close_timeout = kwargs.get(
            "timeout"
        )
        self.closed = True
        await self.incoming.put(None)

    async def emit(
        self,
        payload: dict,
    ) -> None:
        await self.incoming.put(
            json.dumps(payload)
        )


def _settings(
    **overrides,
) -> STTProviderSettings:
    values = {
        "deepgram_api_key": "test-api-key",
        "deepgram_ws_url": "wss://api.deepgram.com/v1/listen",
        "deepgram_model": "nova-3",
        "deepgram_language": "en-US",
        "deepgram_interim_results": True,
        "deepgram_endpointing_ms": 700,
        "deepgram_utterance_end_ms": 1200,
        "deepgram_vad_events": True,
        "deepgram_smart_format": True,
        "deepgram_no_delay": False,
        "stt_connect_timeout_seconds": 5.0,
        "stt_connect_max_retries": 2,
        "stt_connect_retry_backoff_seconds": 0.01,
        "stt_ping_interval_seconds": 20.0,
        "stt_ping_timeout_seconds": 20.0,
        "stt_close_timeout_seconds": 5.0,
        "stt_provider_max_message_bytes": 1_048_576,
        "stt_provider_max_queue_items": 16,
        "stt_event_queue_max_items": 8,
    }
    values.update(overrides)
    return STTProviderSettings(**values)


def _request(
    encoding: str = "pcm_s16le",
) -> STTStreamRequest:
    return STTStreamRequest(
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        audio_format=STTAudioFormat(
            encoding=encoding,
            sample_rate_hz=16_000,
            channels=1,
        ),
    )


@pytest.mark.asyncio
async def test_adapter_rejects_missing_api_key():
    adapter = DeepgramSTTAdapter(
        _settings(
            deepgram_api_key=None
        )
    )

    with pytest.raises(
        STTAdapterError,
        match="API key",
    ):
        await adapter.start_stream(
            _request()
        )


@pytest.mark.asyncio
async def test_adapter_rejects_unsupported_audio_encoding():
    adapter = DeepgramSTTAdapter(
        _settings()
    )

    with pytest.raises(
        STTAdapterError,
        match="not supported",
    ):
        await adapter.start_stream(
            _request(
                encoding="unknown-codec"
            )
        )


@pytest.mark.asyncio
async def test_adapter_opens_authenticated_deepgram_connection(
    monkeypatch,
):
    fake_websocket = FakeDeepgramWebSocket()
    captured = {}

    async def fake_connect(
        uri,
        **kwargs,
    ):
        captured["uri"] = uri
        captured["kwargs"] = kwargs
        return fake_websocket

    import services.deepgram_stt_adapter as module

    monkeypatch.setattr(
        module,
        "connect",
        fake_connect,
    )

    adapter = DeepgramSTTAdapter(
        _settings()
    )

    stream = await adapter.start_stream(
        _request()
    )

    assert isinstance(
        stream,
        DeepgramSTTStream,
    )
    assert "model=nova-3" in captured["uri"]
    assert "interim_results=true" in captured["uri"]
    assert "endpointing=700" in captured["uri"]
    assert "utterance_end_ms=1200" in captured["uri"]
    assert "vad_events=true" in captured["uri"]
    assert "smart_format=true" in captured["uri"]
    assert captured["kwargs"]["additional_headers"] == {
        "Authorization": "Token test-api-key"
    }
    assert captured["kwargs"]["compression"] is None
    assert captured["kwargs"]["max_size"] == 1_048_576

    await stream.close()


@pytest.mark.asyncio
async def test_adapter_retries_transient_connection_failure(
    monkeypatch,
):
    websocket = FakeDeepgramWebSocket()
    attempts = 0

    async def flaky_connect(uri, **kwargs):
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            raise OSError("temporary network failure")

        return websocket

    import services.deepgram_stt_adapter as module

    monkeypatch.setattr(
        module,
        "connect",
        flaky_connect,
    )

    adapter = DeepgramSTTAdapter(
        _settings(
            stt_connect_max_retries=2,
        )
    )

    stream = await adapter.start_stream(
        _request()
    )

    assert attempts == 2
    await stream.close()


@pytest.mark.asyncio
async def test_adapter_exhausts_bounded_connection_retries(
    monkeypatch,
):
    attempts = 0

    async def failing_connect(uri, **kwargs):
        nonlocal attempts
        attempts += 1
        raise OSError("provider unavailable")

    import services.deepgram_stt_adapter as module

    monkeypatch.setattr(
        module,
        "connect",
        failing_connect,
    )

    adapter = DeepgramSTTAdapter(
        _settings(
            stt_connect_max_retries=2,
        )
    )

    with pytest.raises(
        STTAdapterError,
        match="after 3 attempts",
    ):
        await adapter.start_stream(
            _request()
        )

    assert attempts == 3


@pytest.mark.asyncio
async def test_pcm_s16le_encoding_is_mapped_to_deepgram_linear16(
    monkeypatch,
):
    fake_websocket = FakeDeepgramWebSocket()
    captured = {}

    async def fake_connect(
        uri,
        **kwargs,
    ):
        captured["uri"] = uri
        return fake_websocket

    import services.deepgram_stt_adapter as module

    monkeypatch.setattr(
        module,
        "connect",
        fake_connect,
    )

    adapter = DeepgramSTTAdapter(
        _settings()
    )

    stream = await adapter.start_stream(
        _request(
            encoding="pcm_s16le"
        )
    )

    assert "encoding=linear16" in captured["uri"]

    await stream.close()


@pytest.mark.asyncio
async def test_stream_sends_binary_audio():
    websocket = FakeDeepgramWebSocket()

    stream = DeepgramSTTStream(
        websocket=websocket,
        request=_request(),
        settings=_settings(),
    )

    await stream.send_audio(
        b"audio"
    )

    assert websocket.sent == [
        b"audio"
    ]

    await stream.close()


@pytest.mark.asyncio
async def test_stream_reports_unexpected_provider_eof():
    websocket = FakeDeepgramWebSocket()

    stream = DeepgramSTTStream(
        websocket=websocket,
        request=_request(),
        settings=_settings(),
    )

    await websocket.incoming.put(None)

    with pytest.raises(
        STTAdapterError,
        match="connection closed unexpectedly",
    ):
        async for _event in stream.events():
            pass

    await stream.close()


@pytest.mark.asyncio
async def test_stream_finish_sends_finalize_message():
    websocket = FakeDeepgramWebSocket()

    stream = DeepgramSTTStream(
        websocket=websocket,
        request=_request(),
        settings=_settings(),
    )

    await stream.finish()

    assert websocket.sent == [
        '{"type": "Finalize"}'
    ]

    await stream.finish()

    assert websocket.sent == [
        '{"type": "Finalize"}'
    ]

    await stream.close()


@pytest.mark.asyncio
async def test_stream_converts_partial_and_final_results():
    websocket = FakeDeepgramWebSocket()

    stream = DeepgramSTTStream(
        websocket=websocket,
        request=_request(),
        settings=_settings(),
    )

    await websocket.emit(
        {
            "type": "Results",
            "is_final": False,
            "channel": {
                "alternatives": [
                    {
                        "transcript": "set a"
                    }
                ]
            },
        }
    )

    await websocket.emit(
        {
            "type": "Results",
            "is_final": True,
            "speech_final": True,
            "channel": {
                "alternatives": [
                    {
                        "transcript": "set a reminder"
                    }
                ]
            },
        }
    )

    events = []

    async def consume():
        async for event in stream.events():
            events.append(event)

            if event.type == "final":
                return

    consumer = asyncio.create_task(
        consume()
    )

    await asyncio.wait_for(
        consumer,
        timeout=1,
    )

    assert [event.type for event in events] == [
        "partial",
        "final",
    ]
    assert [event.sequence for event in events] == [
        1,
        2,
    ]
    assert events[0].is_end_of_speech is False
    assert events[1].is_end_of_speech is True
    assert all(
        isinstance(
            event,
            STTTranscriptEvent,
        )
        for event in events
    )

    await stream.close()


@pytest.mark.asyncio
async def test_stream_converts_speech_boundaries():
    websocket = FakeDeepgramWebSocket()

    stream = DeepgramSTTStream(
        websocket=websocket,
        request=_request(),
        settings=_settings(),
    )

    await websocket.emit(
        {
            "type": "SpeechStarted",
            "channel": [0, 1],
            "timestamp": 1.25,
        }
    )
    await websocket.emit(
        {
            "type": "Results",
            "is_final": True,
            "speech_final": False,
            "channel": {
                "alternatives": [
                    {
                        "transcript": "hello there"
                    }
                ]
            },
        }
    )
    await websocket.emit(
        {
            "type": "UtteranceEnd",
            "channel": [0, 1],
            "last_word_end": 2.4,
        }
    )

    events = []

    async def consume():
        async for event in stream.events():
            events.append(event)
            if len(events) == 3:
                return

    consumer = asyncio.create_task(consume())

    await asyncio.wait_for(
        consumer,
        timeout=1,
    )

    assert events[0].stream_id == "provider-stream-1"
    assert events[0].timestamp_seconds == 1.25
    assert events[0].sequence == 1
    assert events[1].type == "final"
    assert events[1].sequence == 2
    assert events[1].is_end_of_speech is False
    assert events[2].last_word_end_seconds == 2.4
    assert events[2].sequence == 3

    await stream.close()


@pytest.mark.asyncio
async def test_stream_ignores_stale_utterance_end():
    websocket = FakeDeepgramWebSocket()

    stream = DeepgramSTTStream(
        websocket=websocket,
        request=_request(),
        settings=_settings(),
    )

    await websocket.emit(
        {
            "type": "UtteranceEnd",
            "channel": [0, 1],
            "last_word_end": -1,
        }
    )
    await websocket.emit(
        {
            "type": "Results",
            "is_final": True,
            "speech_final": True,
            "channel": {
                "alternatives": [
                    {
                        "transcript": "hello"
                    }
                ]
            },
        }
    )

    event = None

    async def consume():
        nonlocal event
        async for item in stream.events():
            event = item
            return

    consumer = asyncio.create_task(consume())

    await asyncio.wait_for(consumer, timeout=1)

    assert event is not None
    assert event.type == "final"
    assert event.sequence == 1

    await stream.close()


@pytest.mark.asyncio
async def test_stream_ignores_empty_and_non_result_messages():
    websocket = FakeDeepgramWebSocket()

    stream = DeepgramSTTStream(
        websocket=websocket,
        request=_request(),
        settings=_settings(),
    )

    await websocket.emit(
        {
            "type": "Metadata"
        }
    )
    await websocket.emit(
        {
            "type": "Results",
            "is_final": False,
            "channel": {
                "alternatives": [
                    {
                        "transcript": "   "
                    }
                ]
            },
        }
    )
    await websocket.emit(
        {
            "type": "Results",
            "is_final": True,
            "channel": {
                "alternatives": [
                    {
                        "transcript": "hello"
                    }
                ]
            },
        }
    )

    event = await asyncio.wait_for(
        anext(
            stream.events()
        ),
        timeout=1,
    )

    assert event.text == "hello"

    await stream.close()


@pytest.mark.asyncio
async def test_provider_error_is_exposed_without_leaking_credentials():
    websocket = FakeDeepgramWebSocket()

    stream = DeepgramSTTStream(
        websocket=websocket,
        request=_request(),
        settings=_settings(),
    )

    await websocket.emit(
        {
            "type": "Error",
            "message": "request failed",
            "api_key": "super-secret",
        }
    )

    with pytest.raises(
        STTAdapterError,
        match="request failed",
    ) as exc_info:
        async for _event in stream.events():
            pass

    assert "super-secret" not in str(
        exc_info.value
    )

    await stream.close()


@pytest.mark.asyncio
async def test_cancel_closes_provider_and_blocks_future_audio():
    websocket = FakeDeepgramWebSocket()

    stream = DeepgramSTTStream(
        websocket=websocket,
        request=_request(),
        settings=_settings(),
    )

    await stream.cancel()

    assert websocket.closed is True

    with pytest.raises(
        (
            STTStreamClosedError,
            STTStreamNotActiveError,
        )
    ):
        await stream.send_audio(
            b"late"
        )

    await stream.close()
