from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class VoiceControlMessage(BaseModel):
    type: Literal[
        "turn.start",
        "turn.commit",
        "turn.cancel",
        "session.ping",
        "session.close",
    ]

    turn_id: str | None = None