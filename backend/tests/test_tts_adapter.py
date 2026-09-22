from datetime import datetime, timezone

import pytest

from services.tts_adapter import (
    DEFAULT_MAX_SYNTHESIS_TEXT_CHARS,
    TTSAudioEvent,
    TTSAudioFormat,
    TTSStreamRequest,
)


def test_tts_audio_format_normalizes_and_validates() -> None:
    audio_format = TTSAudioFormat(
        encoding=" PCM_S16LE ",
        sample_rate_hz=24_000,
        channels=1,
    )

    assert audio_format.encoding == "pcm_s16le"
    assert audio_format.sample_rate_hz == 24_000
    assert audio_format.channels == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "encoding": " ",
            "sample_rate_hz": 24_000,
            "channels": 1,
        },
        {
            "encoding": "pcm_s16le",
            "sample_rate_hz": 7_999,
            "channels": 1,
        },
        {
            "encoding": "pcm_s16le",
            "sample_rate_hz": 192_001,
            "channels": 1,
        },
        {
            "encoding": "pcm_s16le",
            "sample_rate_hz": 24_000,
            "channels": 0,
        },
        {
            "encoding": "pcm_s16le",
            "sample_rate_hz": 24_000,
            "channels": 9,
        },
    ],
)
def test_tts_audio_format_rejects_invalid_values(
    kwargs: dict,
) -> None:
    with pytest.raises(ValueError):
        TTSAudioFormat(**kwargs)


def test_tts_stream_request_normalizes_fields() -> None:
    request = TTSStreamRequest(
        user_id=" user-001 ",
        session_id=" session-123 ",
        turn_id=" turn-456 ",
        voice=" nova-default ",
        audio_format=TTSAudioFormat(
            encoding="pcm_s16le",
            sample_rate_hz=24_000,
            channels=1,
        ),
        language=" en-US ",
    )

    assert request.user_id == "user-001"
    assert request.session_id == "session-123"
    assert request.turn_id == "turn-456"
    assert request.voice == "nova-default"
    assert request.language == "en-US"


@pytest.mark.parametrize(
    "field_name",
    [
        "user_id",
        "session_id",
        "turn_id",
        "voice",
    ],
)
def test_tts_stream_request_requires_identity_fields(
    field_name: str,
) -> None:
    values = {
        "user_id": "user-001",
        "session_id": "session-123",
        "turn_id": "turn-456",
        "voice": "nova-default",
        "audio_format": TTSAudioFormat(
            encoding="pcm_s16le",
            sample_rate_hz=24_000,
            channels=1,
        ),
    }
    values[field_name] = " "

    with pytest.raises(ValueError):
        TTSStreamRequest(**values)


def test_tts_stream_request_rejects_blank_language() -> None:
    with pytest.raises(ValueError):
        TTSStreamRequest(
            user_id="user-001",
            session_id="session-123",
            turn_id="turn-456",
            voice="nova-default",
            audio_format=TTSAudioFormat(
                encoding="pcm_s16le",
                sample_rate_hz=24_000,
                channels=1,
            ),
            language=" ",
        )


def test_tts_audio_event_accepts_audio_chunk() -> None:
    created_at = datetime.now(timezone.utc)

    event = TTSAudioEvent(
        stream_id="stream-1",
        turn_id="turn-1",
        sequence=0,
        type="audio",
        audio=b"audio",
        created_at=created_at,
    )

    assert event.type == "audio"
    assert event.audio == b"audio"
    assert event.created_at == created_at


def test_tts_audio_event_accepts_final_marker() -> None:
    event = TTSAudioEvent(
        stream_id="stream-1",
        turn_id="turn-1",
        sequence=1,
        type="final",
        audio=b"",
        created_at=datetime.now(timezone.utc),
    )

    assert event.type == "final"
    assert event.audio == b""


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "sequence": -1,
            "type": "audio",
            "audio": b"audio",
        },
        {
            "sequence": 0,
            "type": "audio",
            "audio": b"",
        },
        {
            "sequence": 0,
            "type": "final",
            "audio": b"audio",
        },
        {
            "sequence": 0,
            "type": "other",
            "audio": b"audio",
        },
    ],
)
def test_tts_audio_event_rejects_invalid_payloads(
    kwargs: dict,
) -> None:
    with pytest.raises(ValueError):
        TTSAudioEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            created_at=datetime.now(timezone.utc),
            **kwargs,
        )


def test_tts_audio_event_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError):
        TTSAudioEvent(
            stream_id="stream-1",
            turn_id="turn-1",
            sequence=0,
            type="audio",
            audio=b"audio",
            created_at=datetime.now(),
        )


def test_default_synthesis_text_limit_is_positive() -> None:
    assert DEFAULT_MAX_SYNTHESIS_TEXT_CHARS > 0
