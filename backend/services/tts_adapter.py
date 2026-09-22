from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final, Literal


TTSAudioEventType = Literal["audio", "final"]
DEFAULT_MAX_SYNTHESIS_TEXT_CHARS: Final[int] = 16_384


class TTSAdapterError(RuntimeError):
    """Base error raised by a TTS adapter or stream."""


class TTSStreamClosedError(TTSAdapterError):
    """Raised when a closed TTS stream is used again."""


class TTSStreamNotActiveError(TTSAdapterError):
    """Raised when a stream operation is invalid for its lifecycle state."""


@dataclass(frozen=True, slots=True)
class TTSAudioFormat:
    """
    Audio format emitted by a TTS stream.

    The transport remains codec-agnostic. A concrete provider adapter is
    responsible for translating the requested output format into the
    provider's synthesis contract.
    """

    encoding: str
    sample_rate_hz: int
    channels: int

    def __post_init__(self) -> None:
        normalized_encoding = self.encoding.strip().lower()

        if not normalized_encoding:
            raise ValueError("encoding cannot be empty.")

        if len(normalized_encoding) > 64:
            raise ValueError("encoding cannot exceed 64 characters.")

        if self.sample_rate_hz < 8_000 or self.sample_rate_hz > 192_000:
            raise ValueError(
                "sample_rate_hz must be between 8000 and 192000."
            )

        if self.channels < 1 or self.channels > 8:
            raise ValueError("channels must be between 1 and 8.")

        object.__setattr__(
            self,
            "encoding",
            normalized_encoding,
        )


@dataclass(frozen=True, slots=True)
class TTSStreamRequest:
    """Identity and synthesis contract for one realtime TTS stream."""

    user_id: str
    session_id: str
    turn_id: str
    voice: str
    audio_format: TTSAudioFormat
    language: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "user_id",
            "session_id",
            "turn_id",
            "voice",
        ):
            value = getattr(self, field_name)

            if not isinstance(value, str):
                raise ValueError(
                    f"{field_name} must be a string."
                )

            normalized = value.strip()

            if not normalized:
                raise ValueError(
                    f"{field_name} cannot be empty."
                )

            if len(normalized) > 128:
                raise ValueError(
                    f"{field_name} cannot exceed 128 characters."
                )

            object.__setattr__(
                self,
                field_name,
                normalized,
            )

        if self.language is not None:
            normalized_language = self.language.strip()

            if not normalized_language:
                raise ValueError(
                    "language cannot be empty when provided."
                )

            if len(normalized_language) > 32:
                raise ValueError(
                    "language cannot exceed 32 characters."
                )

            object.__setattr__(
                self,
                "language",
                normalized_language,
            )


@dataclass(frozen=True, slots=True)
class TTSAudioEvent:
    """
    Ordered audio update emitted by a TTS stream.

    Audio events carry binary output chunks. A final event indicates that
    synthesis for the current text stream is complete and no more audio
    should be emitted for that stream.
    """

    stream_id: str
    turn_id: str
    sequence: int
    type: TTSAudioEventType
    audio: bytes
    created_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "stream_id",
            "turn_id",
        ):
            value = getattr(self, field_name)

            if not isinstance(value, str):
                raise ValueError(
                    f"{field_name} must be a string."
                )

            normalized = value.strip()

            if not normalized:
                raise ValueError(
                    f"{field_name} cannot be empty."
                )

            if len(normalized) > 128:
                raise ValueError(
                    f"{field_name} cannot exceed 128 characters."
                )

            object.__setattr__(
                self,
                field_name,
                normalized,
            )

        if self.sequence < 0:
            raise ValueError(
                "sequence must be non-negative."
            )

        if self.type not in (
            "audio",
            "final",
        ):
            raise ValueError(
                "type must be 'audio' or 'final'."
            )

        if not isinstance(self.audio, bytes):
            raise ValueError(
                "audio must be bytes."
            )

        if self.type == "audio" and not self.audio:
            raise ValueError(
                "audio cannot be empty for an audio event."
            )

        if self.type == "final" and self.audio:
            raise ValueError(
                "final events must not contain audio bytes."
            )

        if self.created_at.tzinfo is None:
            raise ValueError(
                "created_at must be timezone-aware."
            )


class TTSStream(ABC):
    """
    Provider-neutral lifecycle for one realtime TTS stream.

    Implementations must make cancel() promptly stop provider work and make
    close() idempotent so voice-session disconnects can safely clean up.
    """

    @property
    @abstractmethod
    def stream_id(self) -> str:
        """Return the provider-independent stream identifier."""

    @property
    @abstractmethod
    def turn_id(self) -> str:
        """Return the turn identifier bound to this stream."""

    @abstractmethod
    async def send_text(
        self,
        text: str,
    ) -> None:
        """
        Send one text chunk to the synthesis provider.

        Implementations must apply provider-side backpressure or bounded
        buffering rather than allowing unlimited in-memory growth.
        """

    @abstractmethod
    async def events(
        self,
    ) -> AsyncIterator[TTSAudioEvent]:
        """
        Yield ordered binary audio/final events.

        Implementations should terminate iteration after finish(), cancel(),
        or close().
        """

    @abstractmethod
    async def finish(self) -> None:
        """
        Mark normal end-of-input.

        Implementations should allow the provider's final audio and final
        event to be observed through events().
        """

    @abstractmethod
    async def cancel(self) -> None:
        """Cancel provider work and discard unfinished synthesis."""

    @abstractmethod
    async def close(self) -> None:
        """Release all provider resources; safe to call repeatedly."""


class TTSAdapter(ABC):
    """Provider-neutral factory for realtime streaming TTS sessions."""

    @abstractmethod
    async def start_stream(
        self,
        request: TTSStreamRequest,
    ) -> TTSStream:
        """
        Start one synthesis stream for one authenticated NOVA voice turn.

        Implementations must bind the stream to the supplied user/session/turn
        identity and requested output format.
        """


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for adapter event metadata."""
    return datetime.now(timezone.utc)
