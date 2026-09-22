from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from config import VoiceSettings, get_voice_settings
from services.tts_adapter import (
    TTSAudioEvent,
    TTSAudioFormat,
    TTSAdapter,
    TTSStreamRequest,
)
from services.tts_runtime_service import (
    TTSRuntimeError,
    TTSRuntimeService,
)


class VoiceTTSOrchestratorError(RuntimeError):
    """Raised when realtime voice-to-TTS orchestration fails."""


@dataclass
class _VoiceTTSTurn:
    request: TTSStreamRequest
    stream_id: str
    events: asyncio.Queue[
        TTSAudioEvent | Exception | None
    ]
    relay_task: asyncio.Task[None] | None = None
    consumer_claimed: bool = False


class VoiceTTSOrchestrator:
    """
    Bridge one authenticated NOVA voice turn to the TTS runtime.

    The WebSocket owns transport. This service owns the relationship between
    one assistant response turn and one streaming TTS runtime stream.
    """

    def __init__(
        self,
        adapter: TTSAdapter,
        settings: VoiceSettings | None = None,
    ):
        self.settings = (
            settings
            if settings is not None
            else get_voice_settings()
        )
        self.runtime = TTSRuntimeService(
            adapter=adapter,
            settings=self.settings,
        )
        self._turn: _VoiceTTSTurn | None = None

    async def start_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        voice: str,
        audio_format: TTSAudioFormat,
    ) -> str:
        if self._turn is not None:
            raise VoiceTTSOrchestratorError(
                "A voice TTS turn is already active."
            )

        request = TTSStreamRequest(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            voice=voice,
            audio_format=audio_format,
        )

        try:
            stream_id = await self.runtime.start_turn(
                request
            )
        except TTSRuntimeError:
            raise
        except Exception as exc:
            raise VoiceTTSOrchestratorError(
                "Failed to start the voice TTS stream."
            ) from exc

        loop = asyncio.get_running_loop()

        turn = _VoiceTTSTurn(
            request=request,
            stream_id=stream_id,
            events=asyncio.Queue(
                maxsize=(
                    self.settings.voice_tts_event_queue_max_items
                )
            ),
        )

        self._turn = turn
        turn.relay_task = asyncio.create_task(
            self._relay_events(turn)
        )

        return stream_id

    async def send_text(
        self,
        text: str,
    ) -> None:
        turn = self._require_turn()

        try:
            await self.runtime.send_text(
                session_id=turn.request.session_id,
                turn_id=turn.request.turn_id,
                text=text,
            )
        except TTSRuntimeError:
            raise
        except Exception as exc:
            raise VoiceTTSOrchestratorError(
                "Failed to stream assistant text to TTS."
            ) from exc

    async def finish_turn(self) -> None:
        turn = self._require_turn()

        try:
            await self.runtime.finish_turn(
                session_id=turn.request.session_id,
                turn_id=turn.request.turn_id,
            )
        except TTSRuntimeError:
            raise
        except Exception as exc:
            raise VoiceTTSOrchestratorError(
                "Failed to finish the voice TTS stream."
            ) from exc

    async def cancel_turn(self) -> None:
        turn = self._turn

        if turn is None:
            return

        try:
            await self.runtime.cancel_turn(
                session_id=turn.request.session_id,
                turn_id=turn.request.turn_id,
            )
        finally:
            await self._stop_relay(turn)
            self._drain_events(turn.events)
            self._turn = None

    async def close_session(self) -> None:
        turn = self._turn

        if turn is None:
            return

        try:
            await self.runtime.close_session(
                turn.request.session_id
            )
        finally:
            await self._stop_relay(turn)
            self._drain_events(turn.events)
            self._turn = None

    async def events(
        self,
    ) -> AsyncIterator[TTSAudioEvent]:
        turn = self._require_turn()

        if turn.consumer_claimed:
            raise VoiceTTSOrchestratorError(
                "Only one voice TTS event consumer is allowed."
            )

        turn.consumer_claimed = True

        try:
            while True:
                item = await turn.events.get()

                if item is None:
                    return

                if isinstance(item, Exception):
                    await self._cancel_active_turn(turn)
                    self._turn = None

                    if isinstance(
                        item,
                        VoiceTTSOrchestratorError,
                    ):
                        raise item

                    raise VoiceTTSOrchestratorError(
                        "Voice TTS event processing failed."
                    ) from item

                yield item

        finally:
            if self._turn is turn:
                await self._cancel_active_turn(turn)
                self._turn = None

    async def _relay_events(
        self,
        turn: _VoiceTTSTurn,
    ) -> None:
        try:
            async for event in self.runtime.events(
                session_id=turn.request.session_id,
                turn_id=turn.request.turn_id,
            ):
                await turn.events.put(
                    event
                )

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                await turn.events.put(exc)
            except asyncio.CancelledError:
                raise
        finally:
            try:
                await turn.events.put(None)
            except asyncio.CancelledError:
                raise

    async def _cancel_active_turn(
        self,
        turn: _VoiceTTSTurn,
    ) -> None:
        try:
            await self.runtime.cancel_turn(
                session_id=turn.request.session_id,
                turn_id=turn.request.turn_id,
            )
        finally:
            await self._stop_relay(turn)
            self._drain_events(turn.events)

    async def _stop_relay(
        self,
        turn: _VoiceTTSTurn,
    ) -> None:
        task = turn.relay_task

        if task is None:
            return

        turn.relay_task = None

        if not task.done():
            task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

    @staticmethod
    def _drain_events(
        events: asyncio.Queue[
            TTSAudioEvent | Exception | None
        ],
    ) -> None:
        while True:
            try:
                events.get_nowait()
            except asyncio.QueueEmpty:
                return

    def _require_turn(
        self,
    ) -> _VoiceTTSTurn:
        if self._turn is None:
            raise VoiceTTSOrchestratorError(
                "No active voice TTS turn exists."
            )

        return self._turn
