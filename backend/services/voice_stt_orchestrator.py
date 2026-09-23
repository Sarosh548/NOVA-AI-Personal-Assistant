from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from config import VoiceSettings, get_voice_settings
from services.stt_adapter import (
    STTAdapter,
    STTAudioFormat,
    STTSpeechStartedEvent,
    STTStreamEvent,
    STTStreamRequest,
    STTTranscriptEvent,
    STTUtteranceEndEvent,
)
from services.stt_runtime_service import (
    STTRuntimeError,
    STTRuntimeService,
)


class VoiceSTTOrchestratorError(RuntimeError):
    """Raised when realtime voice-to-STT orchestration fails."""


@dataclass
class _VoiceSTTTurn:
    request: STTStreamRequest
    stream_id: str
    events: asyncio.Queue[
        STTTranscriptEvent | Exception | None
    ]
    final_event: asyncio.Future[STTTranscriptEvent]
    final_segments: list[str] = field(default_factory=list)
    speech_started: bool = False
    last_sequence: int = -1
    finish_sequence: int | None = None
    relay_task: asyncio.Task[None] | None = None
    consumer_claimed: bool = False


class VoiceSTTOrchestrator:
    """
    Bridge one authenticated NOVA voice turn to the STT runtime.

    The WebSocket owns transport. This service owns only the relationship
    between one voice turn and one streaming STT runtime stream.
    """

    def __init__(
        self,
        adapter: STTAdapter,
        settings: VoiceSettings | None = None,
    ):
        self.settings = (
            settings
            if settings is not None
            else get_voice_settings()
        )
        self.runtime = STTRuntimeService(
            adapter=adapter,
            settings=self.settings,
        )
        self._turn: _VoiceSTTTurn | None = None

    async def start_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        audio_format: STTAudioFormat,
    ) -> str:
        if self._turn is not None:
            raise VoiceSTTOrchestratorError(
                "A voice STT turn is already active."
            )

        request = STTStreamRequest(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            audio_format=audio_format,
        )

        try:
            stream_id = await self.runtime.start_turn(
                request
            )
        except STTRuntimeError:
            raise
        except Exception as exc:
            raise VoiceSTTOrchestratorError(
                "Failed to start the voice STT stream."
            ) from exc

        loop = asyncio.get_running_loop()
        turn = _VoiceSTTTurn(
            request=request,
            stream_id=stream_id,
            events=asyncio.Queue(
                maxsize=self.settings.voice_stt_event_queue_max_items
            ),
            final_event=loop.create_future(),
        )

        self._turn = turn
        turn.relay_task = asyncio.create_task(
            self._relay_events(turn)
        )

        return stream_id

    async def send_audio(
        self,
        frame: bytes,
    ) -> None:
        turn = self._require_turn()

        try:
            await self.runtime.send_audio(
                session_id=turn.request.session_id,
                turn_id=turn.request.turn_id,
                frame=frame,
            )
        except STTRuntimeError:
            raise
        except Exception as exc:
            raise VoiceSTTOrchestratorError(
                "Failed to stream voice audio to STT."
            ) from exc

    async def finish_turn(
        self,
    ) -> STTTranscriptEvent:
        turn = self._require_turn()

        if turn.final_event.done():
            final_event = turn.final_event.result()

            await self.runtime.close_session(
                turn.request.session_id
            )
            await self._stop_relay(turn)
            self._drain_events(turn.events)
            self._turn = None

            return final_event

        turn.finish_sequence = turn.last_sequence

        try:
            await self.runtime.finish_turn(
                session_id=turn.request.session_id,
                turn_id=turn.request.turn_id,
            )

            final_event = await asyncio.wait_for(
                asyncio.shield(turn.final_event),
                timeout=(
                    self.settings
                    .voice_stt_finalization_timeout_seconds
                ),
            )
        except asyncio.TimeoutError as exc:
            await self._cancel_active_turn(turn)
            self._turn = None
            raise VoiceSTTOrchestratorError(
                "STT final transcript was not received before the timeout."
            ) from exc
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._cancel_active_turn(turn)
            self._turn = None
            raise

        await self.runtime.close_session(
            turn.request.session_id
        )
        await self._stop_relay(turn)
        self._drain_events(turn.events)
        self._turn = None

        return final_event

    async def cancel_turn(self) -> None:
        turn = self._turn
        if turn is None:
            return

        await self._cancel_active_turn(turn)
        self._turn = None

    async def close_session(self) -> None:
        turn = self._turn
        if turn is None:
            return

        await self._cancel_active_turn(turn)
        self._turn = None

    async def events(
        self,
    ) -> AsyncIterator[dict]:
        turn = self._require_turn()

        if turn.consumer_claimed:
            raise VoiceSTTOrchestratorError(
                "Only one voice STT event consumer is allowed."
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
                        VoiceSTTOrchestratorError,
                    ):
                        raise item

                    raise VoiceSTTOrchestratorError(
                        "Voice STT event processing failed."
                    ) from item

                yield self._protocol_event(item)
        finally:
            if self._turn is turn:
                await self._cancel_active_turn(turn)
                self._turn = None

    async def _relay_events(
        self,
        turn: _VoiceSTTTurn,
    ) -> None:
        try:
            async for event in self.runtime.events(
                session_id=turn.request.session_id,
                turn_id=turn.request.turn_id,
            ):
                turn.last_sequence = event.sequence

                if isinstance(event, STTSpeechStartedEvent):
                    turn.speech_started = True

                elif isinstance(event, STTTranscriptEvent):
                    if event.type == "final":
                        turn.final_segments.append(
                            event.text
                        )

                        if (
                            event.is_end_of_speech
                            or (
                                turn.finish_sequence is not None
                                and event.sequence > turn.finish_sequence
                            )
                        ) and not turn.final_event.done():
                            turn.final_event.set_result(
                                self._build_complete_final_event(
                                    turn,
                                    event,
                                )
                            )

                elif (
                    isinstance(event, STTUtteranceEndEvent)
                    and turn.final_segments
                    and not turn.final_event.done()
                ):
                    turn.final_event.set_result(
                        self._build_complete_final_event(
                            turn,
                            event,
                        )
                    )

                await turn.events.put(event)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not turn.final_event.done():
                turn.final_event.set_exception(exc)

            try:
                await turn.events.put(exc)
            except asyncio.CancelledError:
                raise
        finally:
            try:
                await turn.events.put(None)
            except asyncio.CancelledError:
                raise

    @staticmethod
    def _build_complete_final_event(
        turn: _VoiceSTTTurn,
        terminal_event: STTStreamEvent,
    ) -> STTTranscriptEvent:
        return STTTranscriptEvent(
            stream_id=terminal_event.stream_id,
            turn_id=terminal_event.turn_id,
            sequence=terminal_event.sequence,
            type="final",
            text=" ".join(turn.final_segments),
            is_end_of_speech=True,
            created_at=terminal_event.created_at,
        )

    async def _cancel_active_turn(
        self,
        turn: _VoiceSTTTurn,
    ) -> None:
        try:
            await self.runtime.cancel_turn(
                session_id=turn.request.session_id,
                turn_id=turn.request.turn_id,
            )
        finally:
            await self._stop_relay(turn)
            self._drain_events(turn.events)

            if not turn.final_event.done():
                turn.final_event.cancel()

    async def _stop_relay(
        self,
        turn: _VoiceSTTTurn,
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
    def _protocol_event(
        event: STTStreamEvent,
    ) -> dict:
        if isinstance(event, STTSpeechStartedEvent):
            return {
                "type": "speech.started",
                "stream_id": event.stream_id,
                "turn_id": event.turn_id,
                "sequence": event.sequence,
                "timestamp_seconds": event.timestamp_seconds,
                "created_at": event.created_at.isoformat(),
            }

        if isinstance(event, STTUtteranceEndEvent):
            return {
                "type": "transcript.utterance_end",
                "stream_id": event.stream_id,
                "turn_id": event.turn_id,
                "sequence": event.sequence,
                "last_word_end_seconds": event.last_word_end_seconds,
                "created_at": event.created_at.isoformat(),
            }

        return {
            "type": (
                "transcript.final"
                if event.type == "final"
                else "transcript.partial"
            ),
            "stream_id": event.stream_id,
            "turn_id": event.turn_id,
            "sequence": event.sequence,
            "text": event.text,
            "is_end_of_speech": event.is_end_of_speech,
            "created_at": event.created_at.isoformat(),
        }

    def _require_turn(
        self,
    ) -> _VoiceSTTTurn:
        if self._turn is None:
            raise VoiceSTTOrchestratorError(
                "No active voice STT turn exists."
            )
        return self._turn

    @staticmethod
    def _drain_events(
        events: asyncio.Queue[
            STTTranscriptEvent | Exception | None
        ],
    ) -> None:
        while True:
            try:
                events.get_nowait()
            except asyncio.QueueEmpty:
                return
