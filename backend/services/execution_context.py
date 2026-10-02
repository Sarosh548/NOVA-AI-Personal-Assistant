from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExecutionMode(str, Enum):
    INTERACTIVE = "interactive"
    AUTONOMOUS = "autonomous"


@dataclass(frozen=True)
class ExecutionContext:
    """
    Describes where a NOVA execution came from.

    Interactive:
        The user directly asked NOVA to do something.

    Autonomous:
        NOVA is acting because of a background event, scheduler,
        workflow, notification, or another trusted system trigger.

    Voice:
        An interactive request whose response is intended to be spoken
        as a natural realtime conversation.
    """

    mode: ExecutionMode
    voice: bool = False

    @property
    def user_requested(self) -> bool:
        """
        Compatibility flag used by the existing permission layer.
        """
        return self.mode == ExecutionMode.INTERACTIVE

    @property
    def is_interactive(self) -> bool:
        return self.mode == ExecutionMode.INTERACTIVE

    @property
    def is_autonomous(self) -> bool:
        return self.mode == ExecutionMode.AUTONOMOUS

    @property
    def is_voice(self) -> bool:
        return self.voice

    @classmethod
    def interactive(
        cls,
        *,
        voice: bool = False,
    ) -> "ExecutionContext":
        return cls(
            mode=ExecutionMode.INTERACTIVE,
            voice=voice,
        )

    @classmethod
    def autonomous(cls) -> "ExecutionContext":
        return cls(
            mode=ExecutionMode.AUTONOMOUS,
            voice=False,
        )


DEFAULT_INTERACTIVE_CONTEXT = ExecutionContext.interactive()
DEFAULT_AUTONOMOUS_CONTEXT = ExecutionContext.autonomous()