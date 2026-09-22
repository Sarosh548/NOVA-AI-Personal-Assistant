from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from config import VoiceSettings, get_voice_settings
from services.stt_adapter import (
    STTAdapter,
    STTStream,
    STTStreamRequest,
    STTTranscriptEvent,
)


class STTRuntimeError(RuntimeError):
    """Raised when the realtime STT orchestration lifecycle is invalid."""


@dataclass
class _RuntimeTurn:
    request: STTStreamRequest
    stream: STTStream
    event_queue: asyncio.Queue[
        STTTranscriptEvent | Exception | None
    ]
    pump_task: asyncio.Task[None] | None = None
    events_consumer_claimed: bool = False
    finished: bool = False
    cancelled: bool = False
    ended: bool = False


class STTRuntimeService:
    """
    Orchestrate one provider-neutral streaming STT stream per voice session.

    The runtime owns lifecycle and backpressure, but delegates provider I/O
    to STTAdapter/STTStream. It intentionally contains no provider SDK logic,
    LLM behavior, persistence, or voice response generation.
    """

    def __init__(
        self,
        adapter: STTAdapter,
        settings: VoiceSettings | None = None,
    ):
        self.adapter = adapter
        self.settings = (
            settings
            if settings is not None
            else get_voice_settings()
        )
        self._turns: dict[str, _RuntimeTurn] = {}

    async def start_turn(
        self,
        request: STTStreamRequest,
    ) -> str:
        if request.session_id in self._turns:
            raise STTRuntimeError(
                "A realtime STT turn is already active for this session."
            )

        try:
            stream = await self.adapter.start_stream(
                request
            )
        except Exception as exc:
            raise STTRuntimeError(
                "Failed to start the STT stream."
            ) from exc

        if stream.turn_id != request.turn_id:
            await self._safe_close(
                stream
            )
            raise STTRuntimeError(
                "STT adapter returned a stream for a different turn."
            )

        if not isinstance(stream.stream_id, str):
            await self._safe_close(
                stream
            )
            raise STTRuntimeError(
                "STT adapter returned an invalid stream id."
            )

        normalized_stream_id = (
            stream.stream_id.strip()
        )

        if not normalized_stream_id:
            await self._safe_close(
                stream
            )
            raise STTRuntimeError(
                "STT adapter returned an empty stream id."
            )

        turn = _RuntimeTurn(
            request=request,
            stream=stream,
            event_queue=asyncio.Queue(
                maxsize=(
                    self.settings
                    .voice_stt_event_queue_max_items
                )
            ),
        )

        self._turns[request.session_id] = turn

        turn.pump_task = asyncio.create_task(
            self._pump_events(
                turn
            )
        )

        return normalized_stream_id

    async def send_audio(
        self,
        *,
        session_id: str,
        turn_id: str,
        frame: bytes,
    ) -> None:
        turn = self._require_turn(
            session_id,
            turn_id,
        )

        if turn.finished or turn.cancelled:
            raise STTRuntimeError(
                "STT turn is no longer accepting audio."
            )

        if not isinstance(frame, bytes):
            raise STTRuntimeError(
                "STT audio frame must be binary data."
            )

        if not frame:
            raise STTRuntimeError(
                "STT audio frame cannot be empty."
            )

        if len(frame) > (
            self.settings.voice_audio_frame_max_bytes
        ):
            raise STTRuntimeError(
                "STT audio frame exceeds the configured size limit."
            )

        try:
            await turn.stream.send_audio(
                frame
            )
        except Exception as exc:
            raise STTRuntimeError(
                "Failed to forward audio to the STT stream."
            ) from exc

    async def finish_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
    ) -> None:
        turn = self._require_turn(
            session_id,
            turn_id,
        )

        if turn.cancelled:
            raise STTRuntimeError(
                "Cancelled STT turn cannot be finished."
            )

        if turn.finished:
            return

        turn.finished = True

        try:
            await turn.stream.finish()
        except Exception as exc:
            await self._cancel_and_cleanup(
                session_id,
                turn_id,
                turn,
            )
            raise STTRuntimeError(
                "Failed to finish the STT stream."
            ) from exc

    async def cancel_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
    ) -> None:
        turn = self._turns.get(
            session_id
        )

        if turn is None:
            return

        if turn.request.turn_id != turn_id:
            raise STTRuntimeError(
                "The supplied turn id does not match the active STT turn."
            )

        await self._cancel_and_cleanup(
            session_id,
            turn_id,
            turn,
        )

    async def close_session(
        self,
        session_id: str,
    ) -> None:
        turn = self._turns.get(
            session_id
        )

        if turn is None:
            return

        await self._cancel_and_cleanup(
            session_id,
            turn.request.turn_id,
            turn,
        )

    async def events(
        self,
        *,
        session_id: str,
        turn_id: str,
    ) -> AsyncIterator[STTTranscriptEvent]:
        turn = self._require_turn(
            session_id,
            turn_id,
        )

        if turn.events_consumer_claimed:
            raise STTRuntimeError(
                "Only one transcript event consumer is allowed per STT turn."
            )

        turn.events_consumer_claimed = True

        try:
            while True:
                item = await turn.event_queue.get()

                if item is None:
                    return

                if isinstance(
                    item,
                    Exception,
                ):
                    raise STTRuntimeError(
                        "STT stream event pump failed."
                    ) from item

                yield item
        finally:
            if not turn.ended:
                await self._cancel_and_cleanup(
                    session_id,
                    turn_id,
                    turn,
                )
            else:
                await self._close_and_remove(
                    session_id,
                    turn,
                )

    async def _pump_events(
        self,
        turn: _RuntimeTurn,
    ) -> None:
        last_sequence: int | None = None

        try:
            async for event in turn.stream.events():
                self._validate_event(
                    turn,
                    event,
                    last_sequence,
                )

                last_sequence = event.sequence

                await turn.event_queue.put(
                    event
                )

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                await turn.event_queue.put(
                    exc
                )
            except asyncio.CancelledError:
                raise
        finally:
            turn.ended = True

            if not turn.cancelled:
                await turn.event_queue.put(
                    None
                )

    def _validate_event(
        self,
        turn: _RuntimeTurn,
        event: STTTranscriptEvent,
        last_sequence: int | None,
    ) -> None:
        if event.stream_id != turn.stream.stream_id:
            raise STTRuntimeError(
                "STT event stream id does not match the active stream."
            )

        if event.turn_id != turn.request.turn_id:
            raise STTRuntimeError(
                "STT event turn id does not match the active turn."
            )

        if (
            last_sequence is not None
            and event.sequence <= last_sequence
        ):
            raise STTRuntimeError(
                "STT transcript event sequence is not strictly increasing."
            )

    def _require_turn(
        self,
        session_id: str,
        turn_id: str,
    ) -> _RuntimeTurn:
        turn = self._turns.get(
            session_id
        )

        if turn is None:
            raise STTRuntimeError(
                "No active STT turn exists for this session."
            )

        if turn.request.turn_id != turn_id:
            raise STTRuntimeError(
                "The supplied turn id does not match the active STT turn."
            )

        return turn

    async def _cancel_and_cleanup(
        self,
        session_id: str,
        turn_id: str,
        turn: _RuntimeTurn,
    ) -> None:
        if self._turns.get(session_id) is not turn:
            return

        turn.cancelled = True

        try:
            await turn.stream.cancel()
        finally:
            if turn.pump_task is not None:
                turn.pump_task.cancel()

                try:
                    await turn.pump_task
                except asyncio.CancelledError:
                    pass

            # Cancellation intentionally drops queued transcript updates.
            # A cancelled turn must never deliver stale partial results.
            self._drain_queue(
                turn.event_queue
            )

            await self._safe_close(
                turn.stream
            )

            turn.ended = True
            self._turns.pop(
                session_id,
                None,
            )

    async def _close_and_remove(
        self,
        session_id: str,
        turn: _RuntimeTurn,
    ) -> None:
        if self._turns.get(session_id) is not turn:
            return

        await self._safe_close(
            turn.stream
        )

        self._turns.pop(
            session_id,
            None,
        )

    async def _safe_close(
        self,
        stream: STTStream,
    ) -> None:
        try:
            await stream.close()
        except Exception:
            pass

    @staticmethod
    def _drain_queue(
        queue: asyncio.Queue[
            STTTranscriptEvent | Exception | None
        ],
    ) -> None:
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return
