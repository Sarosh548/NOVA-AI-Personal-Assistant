from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


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

    model_config = ConfigDict(
        extra="forbid",
    )
