from __future__ import annotations

import asyncio
import json

import pytest

import services.elevenlabs_tts_adapter as provider_module
from config import TTSProviderSettings
from services.elevenlabs_tts_adapter import (
    ElevenLabsTTSAdapter,
)
from services.tts_adapter import (
    TTSAudioFormat,
    TTSAdapterError,
    TTSStreamClosedError,
    TTSStreamNotActiveError,
    TTSStreamRequest,
)


class FakeWebSocket:
    def __init__(
        self,
        messages: list[str],
    ) -> None:
        self.messages = messages
        self.sent: list[str] = []
        self.closed = False

    async def send(
        self,
        message: str,
    ) -> None:
        self.sent.append(message)

    def __aiter__(self) -> FakeWebSocket:
        self._iterator = iter(self.messages)
        return self

    async def __anext__(self) -> str:
        try:
            return next(self._iterator)
        except StopIteration:
            await asyncio.sleep(0)
            raise StopAsyncIteration

    async def close(
        self,
        **_: object,
    ) -> None:
        self.closed = True


def make_settings(
    **overrides: object,
) -> TTSProviderSettings:
    values = {
        "elevenlabs_api_key": "test-elevenlabs-key",
        "tts_connect_max_retries": 2,
        "tts_connect_retry_backoff_seconds": 0.01,
        "tts_event_queue_max_items": 16,
        "tts_provider_max_message_bytes": 64 * 1024,
        "tts_provider_max_queue_items": 4,
    }
    values.update(overrides)
    return TTSProviderSettings(**values)


def make_request(
    *,
    encoding: str = "pcm_s16le",
    sample_rate_hz: int = 16_000,
    channels: int = 1,
    language: str | None = "en",
) -> TTSStreamRequest:
    return TTSStreamRequest(
        user_id="user-001",
        session_id="session-123",
        turn_id="turn-456",
        voice="voice/example",
        audio_format=TTSAudioFormat(
            encoding=encoding,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
        ),
        language=language,
    )


@pytest.mark.asyncio
async def test_start_stream_builds_secure_uri_and_initializes_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = FakeWebSocket([])
    captured: dict[str, object] = {}

    async def fake_connect(
        uri: str,
        **kwargs: object,
    ) -> FakeWebSocket:
        captured["uri"] = uri
        captured["kwargs"] = kwargs
        return websocket

    monkeypatch.setattr(
        provider_module,
        "connect",
        fake_connect,
    )

    adapter = ElevenLabsTTSAdapter(
        make_settings()
    )

    stream = await adapter.start_stream(
        make_request()
    )

    assert captured["uri"] == (
        "wss://api.elevenlabs.io/v1/text-to-speech/"
        "voice%2Fexample/stream-input?"
        "model_id=eleven_flash_v2_5&"
        "output_format=pcm_16000&"
        "language_code=en"
    )

    assert captured["kwargs"] == {
        "additional_headers": {
            "xi-api-key": "test-elevenlabs-key",
        },
        "compression": None,
        "open_timeout": 10.0,
        "ping_interval": 20.0,
        "ping_timeout": 20.0,
        "close_timeout": 10.0,
        "max_size": 64 * 1024,
        "max_queue": 4,
        "write_limit": 32 * 1024,
    }

    initial_payload = json.loads(
        websocket.sent[0]
    )

    assert initial_payload["text"] == " "
    assert initial_payload["voice_settings"] == {
        "stability": 0.5,
        "similarity_boost": 0.8,
        "speed": 1.0,
        "use_speaker_boost": False,
    }
    assert initial_payload["generation_config"] == {
        "chunk_length_schedule": [
            120,
            160,
            250,
            290,
        ]
    }

    await stream.close()


@pytest.mark.asyncio
async def test_start_stream_retries_transient_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    websockets = [
        FakeWebSocket([]),
        FakeWebSocket([]),
    ]

    async def flaky_connect(
        _uri: str,
        **_kwargs: object,
    ) -> FakeWebSocket:
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            raise OSError("temporary network failure")

        return websockets[1]

    monkeypatch.setattr(
        provider_module,
        "connect",
        flaky_connect,
    )

    stream = await ElevenLabsTTSAdapter(
        make_settings(
            tts_connect_max_retries=2,
        )
    ).start_stream(
        make_request()
    )

    assert attempts == 2
    assert json.loads(
        websockets[1].sent[0]
    )["text"] == " "

    await stream.close()


@pytest.mark.asyncio
async def test_start_stream_exhausts_bounded_connection_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    async def failing_connect(
        _uri: str,
        **_kwargs: object,
    ) -> FakeWebSocket:
        nonlocal attempts
        attempts += 1
        raise OSError("provider unavailable")

    monkeypatch.setattr(
        provider_module,
        "connect",
        failing_connect,
    )

    with pytest.raises(
        TTSAdapterError,
        match="after 3 attempts",
    ):
        await ElevenLabsTTSAdapter(
            make_settings(
                tts_connect_max_retries=2,
            )
        ).start_stream(
            make_request()
        )

    assert attempts == 3


@pytest.mark.asyncio
async def test_stream_relay_decodes_audio_and_emits_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = FakeWebSocket(
        [
            json.dumps(
                {
                    "audio": "SGVsbG8=",
                    "is_final": False,
                }
            ),
            json.dumps(
                {
                    "is_final": True,
                }
            ),
        ]
    )

    async def fake_connect(
        _uri: str,
        **_kwargs: object,
    ) -> FakeWebSocket:
        return websocket

    monkeypatch.setattr(
        provider_module,
        "connect",
        fake_connect,
    )

    stream = await ElevenLabsTTSAdapter(
        make_settings()
    ).start_stream(
        make_request()
    )

    await stream.send_text(
        "Hello NOVA"
    )

    assert json.loads(
        websocket.sent[-1]
    ) == {
        "text": "Hello NOVA ",
    }

    await stream.finish()

    events = [
        event
        async for event in stream.events()
    ]

    assert [event.type for event in events] == [
        "audio",
        "final",
    ]
    assert events[0].audio == b"Hello"
    assert events[0].sequence == 1
    assert events[1].audio == b""
    assert events[1].sequence == 2

    await stream.close()


@pytest.mark.asyncio
async def test_stream_maps_provider_error_to_adapter_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = FakeWebSocket(
        [
            json.dumps(
                {
                    "error": "provider rejected request",
                }
            )
        ]
    )

    async def fake_connect(
        _uri: str,
        **_kwargs: object,
    ) -> FakeWebSocket:
        return websocket

    monkeypatch.setattr(
        provider_module,
        "connect",
        fake_connect,
    )

    stream = await ElevenLabsTTSAdapter(
        make_settings()
    ).start_stream(
        make_request()
    )

    with pytest.raises(
        TTSAdapterError,
        match="provider rejected request",
    ):
        async for _event in stream.events():
            pass


@pytest.mark.asyncio
async def test_stream_rejects_invalid_audio_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = FakeWebSocket(
        [
            json.dumps(
                {
                    "audio": "%%%invalid%%%",
                }
            )
        ]
    )

    async def fake_connect(
        _uri: str,
        **_kwargs: object,
    ) -> FakeWebSocket:
        return websocket

    monkeypatch.setattr(
        provider_module,
        "connect",
        fake_connect,
    )

    stream = await ElevenLabsTTSAdapter(
        make_settings()
    ).start_stream(
        make_request()
    )

    with pytest.raises(
        TTSAdapterError,
        match="invalid audio data",
    ):
        async for _event in stream.events():
            pass


@pytest.mark.asyncio
async def test_stream_requires_active_lifecycle() -> None:
    websocket = FakeWebSocket([])

    stream = provider_module.ElevenLabsTTSStream(
        websocket=websocket,
        request=make_request(),
        settings=make_settings(),
    )

    await stream.finish()

    with pytest.raises(
        TTSStreamNotActiveError,
    ):
        await stream.send_text(
            "later"
        )

    await stream.close()


@pytest.mark.asyncio
async def test_stream_rejects_text_after_close() -> None:
    websocket = FakeWebSocket([])

    stream = provider_module.ElevenLabsTTSStream(
        websocket=websocket,
        request=make_request(),
        settings=make_settings(),
    )

    await stream.close()

    with pytest.raises(
        TTSStreamClosedError,
    ):
        await stream.send_text(
            "hello"
        )


@pytest.mark.asyncio
async def test_cancel_stops_receiver_and_closes_socket() -> None:
    websocket = FakeWebSocket([])

    stream = provider_module.ElevenLabsTTSStream(
        websocket=websocket,
        request=make_request(),
        settings=make_settings(),
    )

    await stream.cancel()

    assert websocket.closed is True

    with pytest.raises(
        TTSStreamNotActiveError,
    ):
        await stream.send_text(
            "hello"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "audio_format",
    [
        TTSAudioFormat(
            encoding="pcm_s16le",
            sample_rate_hz=8_000,
            channels=1,
        ),
        TTSAudioFormat(
            encoding="pcm_s16le",
            sample_rate_hz=48_000,
            channels=1,
        ),
        TTSAudioFormat(
            encoding="opus",
            sample_rate_hz=48_000,
            channels=1,
        ),
    ],
)
async def test_unsupported_audio_format_is_rejected(
    audio_format: TTSAudioFormat,
) -> None:
    adapter = ElevenLabsTTSAdapter(
        make_settings()
    )

    request = TTSStreamRequest(
        user_id="user-001",
        session_id="session-123",
        turn_id="turn-456",
        voice="nova",
        audio_format=audio_format,
    )

    with pytest.raises(
        TTSAdapterError,
        match="Audio format is not supported",
    ):
        await adapter.start_stream(
            request
        )


@pytest.mark.asyncio
async def test_stereo_audio_is_rejected_with_specific_error() -> None:
    adapter = ElevenLabsTTSAdapter(
        make_settings()
    )

    with pytest.raises(
        TTSAdapterError,
        match="currently requires mono audio",
    ):
        await adapter.start_stream(
            make_request(
                channels=2
            )
        )



@pytest.mark.asyncio
async def test_missing_api_key_is_rejected() -> None:
    adapter = ElevenLabsTTSAdapter(
        make_settings(
            elevenlabs_api_key=None
        )
    )

    with pytest.raises(
        TTSAdapterError,
        match="API key is not configured",
    ):
        await adapter.start_stream(
            make_request()
        )


@pytest.mark.asyncio
async def test_connection_failure_is_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_connect(
        _uri: str,
        **_kwargs: object,
    ) -> FakeWebSocket:
        raise OSError(
            "network unavailable"
        )

    monkeypatch.setattr(
        provider_module,
        "connect",
        fake_connect,
    )

    with pytest.raises(
        TTSAdapterError,
        match="connection failed",
    ):
        await ElevenLabsTTSAdapter(
            make_settings()
        ).start_stream(
            make_request()
        )


def test_output_format_mapping() -> None:
    adapter = ElevenLabsTTSAdapter(
        make_settings()
    )

    assert adapter._output_format(
        TTSAudioFormat(
            encoding="PCM_S16LE",
            sample_rate_hz=24_000,
            channels=1,
        )
    ) == "pcm_24000"

    assert adapter._output_format(
        TTSAudioFormat(
            encoding="mulaw",
            sample_rate_hz=8_000,
            channels=1,
        )
    ) == "ulaw_8000"


def test_chunk_schedule_validation() -> None:
    settings = make_settings(
        elevenlabs_chunk_length_schedule="120, 160, 250"
    )

    assert settings.chunk_length_schedule() == (
        120,
        160,
        250,
    )

    invalid = make_settings(
        elevenlabs_chunk_length_schedule="0,160"
    )

    with pytest.raises(
        ValueError,
        match="positive",
    ):
        invalid.chunk_length_schedule()
