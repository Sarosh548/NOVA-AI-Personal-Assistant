from __future__ import annotations

import time

import pytest

from config import VoiceSettings
from services.voice_session_service import (
    VoiceProtocolError,
    VoiceSessionService,
)


def _settings(
    **overrides,
) -> VoiceSettings:
    values = {
        "voice_control_message_max_bytes": 1024,
        "voice_audio_frame_max_bytes": 65536,
        "voice_turn_audio_max_bytes": 65536,
        "voice_turn_max_frames": 4,
        "voice_session_idle_timeout_seconds": 60,
        "voice_turn_max_duration_seconds": 30,
    }

    values.update(overrides)

    return VoiceSettings(**values)


def test_session_can_start_append_and_commit_turn():
    service = VoiceSessionService(
        settings=_settings()
    )

    session = service.create_session(
        "user-1"
    )

    started = service.start_turn(
        session,
        "turn-1",
    )

    assert started["type"] == "turn.started"
    assert started["turn_id"] == "turn-1"

    service.append_audio_frame(
        session,
        b"1234",
    )

    service.append_audio_frame(
        session,
        b"5678",
    )

    committed, audio = service.commit_turn(
        session,
        "turn-1",
    )

    assert committed["type"] == "turn.committed"
    assert committed["turn_id"] == "turn-1"
    assert committed["audio_frames"] == 2
    assert committed["audio_bytes"] == 8
    assert audio == b"12345678"
    assert session.active_turn is None


def test_second_turn_cannot_start_while_one_is_active():
    service = VoiceSessionService(
        settings=_settings()
    )

    session = service.create_session(
        "user-1"
    )

    service.start_turn(
        session,
        "turn-1",
    )

    with pytest.raises(
        VoiceProtocolError
    ) as exc_info:
        service.start_turn(
            session,
            "turn-2",
        )

    assert exc_info.value.code == (
        "turn_already_active"
    )


def test_audio_frame_size_is_bounded():
    service = VoiceSessionService(
        settings=_settings(
            voice_audio_frame_max_bytes=1024
        )
    )

    session = service.create_session(
        "user-1"
    )

    service.start_turn(
        session,
        "turn-1",
    )

    with pytest.raises(
        VoiceProtocolError
    ) as exc_info:
        service.append_audio_frame(
            session,
            b"x" * 1025,
        )

    assert exc_info.value.code == (
        "audio_frame_too_large"
    )


def test_turn_audio_total_is_bounded():
    service = VoiceSessionService(
        settings=_settings(
            voice_audio_frame_max_bytes=65536,
            voice_turn_audio_max_bytes=65536,
        )
    )

    session = service.create_session(
        "user-1"
    )

    service.start_turn(
        session,
        "turn-1",
    )

    service.append_audio_frame(
        session,
        b"a" * 32768,
    )

    with pytest.raises(
        VoiceProtocolError
    ) as exc_info:
        service.append_audio_frame(
            session,
            b"b" * 32769,
        )

    assert exc_info.value.code == (
        "turn_audio_limit_exceeded"
    )

    assert session.active_turn is None


def test_turn_frame_count_is_bounded():
    service = VoiceSessionService(
        settings=_settings(
            voice_audio_frame_max_bytes=1024,
            voice_turn_max_frames=2,
        )
    )

    session = service.create_session(
        "user-1"
    )

    service.start_turn(
        session,
        "turn-1",
    )

    service.append_audio_frame(
        session,
        b"12",
    )

    service.append_audio_frame(
        session,
        b"34",
    )

    with pytest.raises(
        VoiceProtocolError
    ) as exc_info:
        service.append_audio_frame(
            session,
            b"56",
        )

    assert exc_info.value.code == (
        "audio_frame_limit_exceeded"
    )


def test_response_generation_invalidates_stale_execution():
    service = VoiceSessionService(
        settings=_settings()
    )

    session = service.create_session(
        "user-1"
    )

    first_generation = service.begin_response(
        session,
        "turn-1",
    )

    assert service.is_response_current(
        session,
        turn_id="turn-1",
        generation=first_generation,
    )

    service.invalidate_response(
        session
    )

    assert not service.is_response_current(
        session,
        turn_id="turn-1",
        generation=first_generation,
    )

    second_generation = service.begin_response(
        session,
        "turn-2",
    )

    assert second_generation > first_generation
    assert not service.is_response_current(
        session,
        turn_id="turn-1",
        generation=first_generation,
    )
    assert service.is_response_current(
        session,
        turn_id="turn-2",
        generation=second_generation,
    )


def test_turn_can_be_cancelled():
    service = VoiceSessionService(
        settings=_settings()
    )

    session = service.create_session(
        "user-1"
    )

    service.start_turn(
        session,
        "turn-1",
    )

    service.append_audio_frame(
        session,
        b"1234",
    )

    event = service.cancel_turn(
        session,
        "turn-1",
    )

    assert event == {
        "type": "turn.cancelled",
        "turn_id": "turn-1",
    }

    assert session.active_turn is None


def test_wrong_turn_id_cannot_commit_or_cancel():
    service = VoiceSessionService(
        settings=_settings()
    )

    session = service.create_session(
        "user-1"
    )

    service.start_turn(
        session,
        "turn-1",
    )

    with pytest.raises(
        VoiceProtocolError
    ) as commit_error:
        service.commit_turn(
            session,
            "turn-2",
        )

    assert commit_error.value.code == (
        "turn_id_mismatch"
    )

    with pytest.raises(
        VoiceProtocolError
    ) as cancel_error:
        service.cancel_turn(
            session,
            "turn-2",
        )

    assert cancel_error.value.code == (
        "turn_id_mismatch"
    )

    assert session.active_turn is not None


def test_sessions_are_isolated():
    service = VoiceSessionService(
        settings=_settings()
    )

    first = service.create_session(
        "user-1"
    )
    second = service.create_session(
        "user-2"
    )

    service.start_turn(
        first,
        "first-turn",
    )

    service.start_turn(
        second,
        "second-turn",
    )

    service.append_audio_frame(
        first,
        b"first",
    )

    service.append_audio_frame(
        second,
        b"second",
    )

    first_event, first_audio = (
        service.commit_turn(
            first,
            "first-turn",
        )
    )

    second_event, second_audio = (
        service.commit_turn(
            second,
            "second-turn",
        )
    )

    assert first_event["turn_id"] == (
        "first-turn"
    )
    assert second_event["turn_id"] == (
        "second-turn"
    )

    assert first_audio == b"first"
    assert second_audio == b"second"


def test_turn_times_out():
    service = VoiceSessionService(
        settings=_settings(
            voice_turn_max_duration_seconds=1
        )
    )

    session = service.create_session(
        "user-1"
    )

    service.start_turn(
        session,
        "turn-1",
    )

    time.sleep(1.05)

    with pytest.raises(
        VoiceProtocolError
    ) as exc_info:
        service.append_audio_frame(
            session,
            b"1234",
        )

    assert exc_info.value.code == (
        "turn_timeout"
    )

    assert session.active_turn is None