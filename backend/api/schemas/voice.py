from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VoiceAudioFormat(BaseModel):
    encoding: str = Field(
        min_length=1,
        max_length=64,
    )
    sample_rate_hz: int = Field(
        ge=8_000,
        le=192_000,
    )
    channels: int = Field(
        ge=1,
        le=8,
    )

    model_config = ConfigDict(
        extra="forbid",
    )


class VoiceControlMessage(BaseModel):
    type: Literal[
        "session.authenticate",
        "turn.start",
        "turn.commit",
        "turn.cancel",
        "session.ping",
        "session.close",
    ]

    turn_id: str | None = None
    access_token: str | None = None
    audio_format: VoiceAudioFormat | None = None

    model_config = ConfigDict(
        extra="forbid",
    )
