from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
import time
from uuid import uuid4

from config import (
    VoiceSettings,
    get_voice_settings,
)


class VoiceProtocolError(ValueError):
    """Raised when a voice session receives an invalid operation."""

    def __init__(
        self,
        code: str,
        message: str,
    ):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class VoiceTurn:
    turn_id: str
    started_at: datetime
    started_monotonic: float
    audio_buffer: bytearray = field(
        default_factory=bytearray
    )
    audio_frames: int = 0


@dataclass
class VoiceSession:
    session_id: str
    user_id: str
    connected_at: datetime
    conversation_id: int | None = None
    active_turn: VoiceTurn | None = None
    response_generation: int = 0
    active_response_turn_id: str | None = None
    response_lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
        compare=False,
    )


class VoiceSessionService:
    """
    Manage one authenticated realtime NOVA voice session.

    This milestone intentionally keeps session state in memory.
    The session owns only bounded audio data for the active turn.
    No LLM, STT, TTS, database, or execution behavior lives here.
    """

    def __init__(
        self,
        settings: VoiceSettings | None = None,
    ):
        self.settings = (
            settings
            if settings is not None
            else get_voice_settings()
        )

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(
            timezone.utc
        )

    def create_session(
        self,
        user_id: str,
    ) -> VoiceSession:
        normalized_user_id = str(
            user_id
        ).strip()

        if not normalized_user_id:
            raise ValueError(
                "user_id cannot be empty."
            )

        return VoiceSession(
            session_id=str(uuid4()),
            user_id=normalized_user_id,
            connected_at=self._utc_now(),
        )

    def _normalize_turn_id(
        self,
        turn_id: str | None,
    ) -> str:
        if not isinstance(
            turn_id,
            str,
        ):
            raise VoiceProtocolError(
                "invalid_turn_id",
                "turn_id must be a string.",
            )

        normalized = turn_id.strip()

        if not normalized:
            raise VoiceProtocolError(
                "invalid_turn_id",
                "turn_id cannot be empty.",
            )

        if len(normalized) > 128:
            raise VoiceProtocolError(
                "invalid_turn_id",
                "turn_id cannot exceed 128 characters.",
            )

        return normalized

    def start_turn(
        self,
        session: VoiceSession,
        turn_id: str | None,
    ) -> dict:
        if session.active_turn is not None:
            raise VoiceProtocolError(
                "turn_already_active",
                "A voice turn is already active.",
            )

        normalized_turn_id = (
            self._normalize_turn_id(
                turn_id
            )
        )

        now = self._utc_now()

        session.active_turn = VoiceTurn(
            turn_id=normalized_turn_id,
            started_at=now,
            started_monotonic=time.monotonic(),
        )

        return {
            "type": "turn.started",
            "turn_id": normalized_turn_id,
            "started_at": now.isoformat(),
        }

    def append_audio_frame(
        self,
        session: VoiceSession,
        frame: bytes,
    ) -> None:
        turn = session.active_turn

        if turn is None:
            raise VoiceProtocolError(
                "no_active_turn",
                "Audio cannot be received without an active turn.",
            )

        if not isinstance(frame, bytes):
            raise VoiceProtocolError(
                "invalid_audio_frame",
                "Audio frame must be binary data.",
            )

        if not frame:
            raise VoiceProtocolError(
                "empty_audio_frame",
                "Audio frame cannot be empty.",
            )

        if len(frame) > (
            self.settings.voice_audio_frame_max_bytes
        ):
            raise VoiceProtocolError(
                "audio_frame_too_large",
                "Audio frame exceeds the configured size limit.",
            )

        elapsed = (
            time.monotonic()
            - turn.started_monotonic
        )

        if elapsed > (
            self.settings.voice_turn_max_duration_seconds
        ):
            session.active_turn = None
            raise VoiceProtocolError(
                "turn_timeout",
                "Voice turn exceeded the maximum duration.",
            )

        if (
            turn.audio_frames
            >= self.settings.voice_turn_max_frames
        ):
            session.active_turn = None
            raise VoiceProtocolError(
                "audio_frame_limit_exceeded",
                "Voice turn exceeded the maximum frame count.",
            )

        next_audio_size = (
            len(turn.audio_buffer)
            + len(frame)
        )

        if next_audio_size > (
            self.settings.voice_turn_audio_max_bytes
        ):
            session.active_turn = None
            raise VoiceProtocolError(
                "turn_audio_limit_exceeded",
                "Voice turn exceeded the maximum audio size.",
            )

        turn.audio_buffer.extend(frame)
        turn.audio_frames += 1

    def commit_turn(
        self,
        session: VoiceSession,
        turn_id: str | None,
    ) -> tuple[dict, bytes]:
        turn = session.active_turn

        if turn is None:
            raise VoiceProtocolError(
                "no_active_turn",
                "There is no active voice turn to commit.",
            )

        normalized_turn_id = (
            self._normalize_turn_id(
                turn_id
            )
        )

        if normalized_turn_id != turn.turn_id:
            raise VoiceProtocolError(
                "turn_id_mismatch",
                "The supplied turn_id does not match the active turn.",
            )

        elapsed = (
            time.monotonic()
            - turn.started_monotonic
        )

        if elapsed > (
            self.settings.voice_turn_max_duration_seconds
        ):
            session.active_turn = None
            raise VoiceProtocolError(
                "turn_timeout",
                "Voice turn exceeded the maximum duration.",
            )

        audio_data = bytes(
            turn.audio_buffer
        )

        duration_ms = int(
            max(
                0.0,
                elapsed,
            )
            * 1000
        )

        event = {
            "type": "turn.committed",
            "turn_id": turn.turn_id,
            "audio_frames": turn.audio_frames,
            "audio_bytes": len(audio_data),
            "duration_ms": duration_ms,
        }

        session.active_turn = None

        return event, audio_data

    def cancel_turn(
        self,
        session: VoiceSession,
        turn_id: str | None,
    ) -> dict:
        turn = session.active_turn

        if turn is None:
            raise VoiceProtocolError(
                "no_active_turn",
                "There is no active voice turn to cancel.",
            )

        normalized_turn_id = (
            self._normalize_turn_id(
                turn_id
            )
        )

        if normalized_turn_id != turn.turn_id:
            raise VoiceProtocolError(
                "turn_id_mismatch",
                "The supplied turn_id does not match the active turn.",
            )

        session.active_turn = None

        return {
            "type": "turn.cancelled",
            "turn_id": normalized_turn_id,
        }

    def begin_response(
        self,
        session: VoiceSession,
        turn_id: str,
    ) -> int:
        normalized_turn_id = (
            self._normalize_turn_id(
                turn_id
            )
        )

        with session.response_lock:
            session.response_generation += 1
            session.active_response_turn_id = (
                normalized_turn_id
            )
            return session.response_generation

    def invalidate_response(
        self,
        session: VoiceSession,
    ) -> None:
        with session.response_lock:
            session.response_generation += 1
            session.active_response_turn_id = None

    def is_response_current(
        self,
        session: VoiceSession,
        *,
        turn_id: str,
        generation: int,
    ) -> bool:
        normalized_turn_id = (
            self._normalize_turn_id(
                turn_id
            )
        )

        with session.response_lock:
            return (
                session.response_generation == generation
                and session.active_response_turn_id
                == normalized_turn_id
            )

    def close_session(
        self,
        session: VoiceSession,
    ) -> None:
        self.invalidate_response(
            session
        )
        session.active_turn = None