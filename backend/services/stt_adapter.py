from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final, Literal


STTEventType = Literal["partial", "final"]
DEFAULT_MAX_TRANSCRIPT_CHARS: Final[int] = 8_192


class STTAdapterError(RuntimeError):
    """Base error raised by an STT adapter or stream."""


class STTStreamClosedError(STTAdapterError):
    """Raised when a closed STT stream is used again."""


class STTStreamNotActiveError(STTAdapterError):
    """Raised when a stream operation is invalid for its lifecycle state."""


@dataclass(frozen=True, slots=True)
class STTAudioFormat:
    """
    Audio format delivered to an STT stream.

    The transport remains codec-agnostic. A concrete provider adapter is
    responsible for translating the declared format into the provider's
    streaming input contract.
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
class STTStreamRequest:
    """Identity and audio contract for one streaming transcription turn."""

    user_id: str
    session_id: str
    turn_id: str
    audio_format: STTAudioFormat

    def __post_init__(self) -> None:
        for field_name in (
            "user_id",
            "session_id",
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


@dataclass(frozen=True, slots=True)
class STTTranscriptEvent:
    """
    Ordered transcript update emitted by an STT stream.

    Partial events can supersede an earlier partial event. A final event
    represents the completed transcript for the current turn segment.
    """

    stream_id: str
    turn_id: str
    sequence: int
    type: STTEventType
    text: str
    created_at: datetime
    is_end_of_speech: bool = False

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
            "partial",
            "final",
        ):
            raise ValueError(
                "type must be 'partial' or 'final'."
            )

        normalized_text = self.text.strip()

        if not normalized_text:
            raise ValueError(
                "text cannot be empty."
            )

        if len(normalized_text) > DEFAULT_MAX_TRANSCRIPT_CHARS:
            raise ValueError(
                "text cannot exceed the default transcript size limit."
            )

        object.__setattr__(
            self,
            "text",
            normalized_text,
        )

        if self.created_at.tzinfo is None:
            raise ValueError(
                "created_at must be timezone-aware."
            )


class STTStream(ABC):
    """
    Provider-neutral lifecycle for one realtime STT stream.

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
    async def send_audio(
        self,
        frame: bytes,
    ) -> None:
        """
        Send one binary audio frame to the provider.

        The method must apply provider-side backpressure or bounded buffering
        rather than allowing unlimited in-memory growth.
        """

    @abstractmethod
    async def events(
        self,
    ) -> AsyncIterator[STTTranscriptEvent]:
        """
        Yield ordered partial/final transcript events.

        Implementations should terminate iteration after finish(), cancel(),
        or close().
        """

    @abstractmethod
    async def finish(self) -> None:
        """
        Mark normal end-of-input.

        Implementations should allow a provider's final transcript event to
        be observed through events().
        """

    @abstractmethod
    async def cancel(self) -> None:
        """Cancel provider work and discard the unfinished turn."""

    @abstractmethod
    async def close(self) -> None:
        """Release all provider resources; must be safe to call repeatedly."""


class STTAdapter(ABC):
    """Provider-neutral factory for realtime streaming STT sessions."""

    @abstractmethod
    async def start_stream(
        self,
        request: STTStreamRequest,
    ) -> STTStream:
        """
        Start one stream for one authenticated NOVA voice turn.

        Implementations must bind the stream to the supplied user/session/turn
        identity and negotiated audio format.
        """


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for adapter event metadata."""
    return datetime.now(timezone.utc)
