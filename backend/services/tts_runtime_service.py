from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from config import VoiceSettings, get_voice_settings
from services.tts_adapter import (
    DEFAULT_MAX_SYNTHESIS_TEXT_CHARS,
    TTSAudioEvent,
    TTSAdapter,
    TTSStream,
    TTSStreamRequest,
)


class TTSRuntimeError(RuntimeError):
    """Raised when the realtime TTS orchestration lifecycle is invalid."""


@dataclass
class _RuntimeTurn:
    request: TTSStreamRequest
    stream: TTSStream
    event_queue: asyncio.Queue[
        TTSAudioEvent | Exception | None
    ]
    pump_task: asyncio.Task[None] | None = None
    events_consumer_claimed: bool = False
    finished: bool = False
    cancelled: bool = False
    ended: bool = False
    final_event_seen: bool = False


class TTSRuntimeService:
    """
    Orchestrate one provider-neutral streaming TTS stream per voice session.

    The runtime owns lifecycle, bounded buffering, event ordering and output
    chunk limits. Provider-specific websocket/SDK behavior stays inside the
    TTSAdapter implementation.
    """

    def __init__(
        self,
        adapter: TTSAdapter,
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
        request: TTSStreamRequest,
    ) -> str:
        if request.session_id in self._turns:
            raise TTSRuntimeError(
                "A realtime TTS turn is already active for this session."
            )

        try:
            stream = await self.adapter.start_stream(
                request
            )
        except Exception as exc:
            raise TTSRuntimeError(
                "Failed to start the TTS stream."
            ) from exc

        if stream.turn_id != request.turn_id:
            await self._safe_close(stream)
            raise TTSRuntimeError(
                "TTS adapter returned a stream for a different turn."
            )

        if not isinstance(stream.stream_id, str):
            await self._safe_close(stream)
            raise TTSRuntimeError(
                "TTS adapter returned an invalid stream id."
            )

        stream_id = stream.stream_id.strip()

        if not stream_id:
            await self._safe_close(stream)
            raise TTSRuntimeError(
                "TTS adapter returned an empty stream id."
            )

        turn = _RuntimeTurn(
            request=request,
            stream=stream,
            event_queue=asyncio.Queue(
                maxsize=(
                    self.settings.voice_tts_event_queue_max_items
                )
            ),
        )

        self._turns[request.session_id] = turn

        turn.pump_task = asyncio.create_task(
            self._pump_events(turn)
        )

        return stream_id

    async def send_text(
        self,
        *,
        session_id: str,
        turn_id: str,
        text: str,
    ) -> None:
        turn = self._require_turn(
            session_id,
            turn_id,
        )

        if turn.finished or turn.cancelled:
            raise TTSRuntimeError(
                "TTS turn is no longer accepting text."
            )

        if not isinstance(text, str):
            raise TTSRuntimeError(
                "TTS synthesis text must be a string."
            )

        normalized_text = text.strip()

        if not normalized_text:
            raise TTSRuntimeError(
                "TTS synthesis text cannot be empty."
            )

        if len(normalized_text) > DEFAULT_MAX_SYNTHESIS_TEXT_CHARS:
            raise TTSRuntimeError(
                "TTS synthesis text exceeds the configured size limit."
            )

        try:
            await turn.stream.send_text(
                normalized_text
            )
        except Exception as exc:
            raise TTSRuntimeError(
                "Failed to forward text to the TTS stream."
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
            raise TTSRuntimeError(
                "Cancelled TTS turn cannot be finished."
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
            raise TTSRuntimeError(
                "Failed to finish the TTS stream."
            ) from exc

    async def cancel_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
    ) -> None:
        turn = self._turns.get(session_id)

        if turn is None:
            return

        if turn.request.turn_id != turn_id:
            raise TTSRuntimeError(
                "The supplied turn id does not match the active TTS turn."
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
        turn = self._turns.get(session_id)

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
    ) -> AsyncIterator[TTSAudioEvent]:
        turn = self._require_turn(
            session_id,
            turn_id,
        )

        if turn.events_consumer_claimed:
            raise TTSRuntimeError(
                "Only one audio event consumer is allowed per TTS turn."
            )

        turn.events_consumer_claimed = True

        try:
            while True:
                item = await turn.event_queue.get()

                if item is None:
                    return

                if isinstance(item, Exception):
                    await self._cancel_and_cleanup(
                        session_id,
                        turn_id,
                        turn,
                    )

                    if isinstance(
                        item,
                        TTSRuntimeError,
                    ):
                        raise item

                    raise TTSRuntimeError(
                        "TTS stream event pump failed."
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
        pump_failed = False

        try:
            async for event in turn.stream.events():
                self._validate_event(
                    turn,
                    event,
                    last_sequence,
                )

                if event.type == "audio":
                    if len(event.audio) > (
                        self.settings.voice_tts_audio_chunk_max_bytes
                    ):
                        raise TTSRuntimeError(
                            "TTS audio chunk exceeds the configured size limit."
                        )

                if event.type == "final":
                    if turn.final_event_seen:
                        raise TTSRuntimeError(
                            "TTS final event was emitted more than once."
                        )

                    turn.final_event_seen = True

                last_sequence = event.sequence

                try:
                    await asyncio.wait_for(
                        turn.event_queue.put(
                            event
                        ),
                        timeout=(
                            self.settings
                            .voice_event_queue_enqueue_timeout_seconds
                        ),
                    )
                except asyncio.TimeoutError as exc:
                    raise TTSRuntimeError(
                        "TTS event queue backpressure deadline was exceeded."
                    ) from exc

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            pump_failed = True
            self._drain_queue(
                turn.event_queue
            )

            try:
                await turn.event_queue.put(
                    exc
                )
            except asyncio.CancelledError:
                raise
        finally:
            turn.ended = True

            if not turn.cancelled and not pump_failed:
                try:
                    await asyncio.wait_for(
                        turn.event_queue.put(
                            None
                        ),
                        timeout=(
                            self.settings
                            .voice_event_queue_enqueue_timeout_seconds
                        ),
                    )
                except asyncio.TimeoutError:
                    self._drain_queue(
                        turn.event_queue
                    )

                    await turn.event_queue.put(
                        TTSRuntimeError(
                            "TTS event queue backpressure deadline was exceeded."
                        )
                    )

    @staticmethod
    def _validate_event(
        turn: _RuntimeTurn,
        event: TTSAudioEvent,
        last_sequence: int | None,
    ) -> None:
        if event.stream_id != turn.stream.stream_id:
            raise TTSRuntimeError(
                "TTS event stream id does not match the active stream."
            )

        if event.turn_id != turn.request.turn_id:
            raise TTSRuntimeError(
                "TTS event turn id does not match the active turn."
            )

        if (
            last_sequence is not None
            and event.sequence <= last_sequence
        ):
            raise TTSRuntimeError(
                "TTS audio event sequence is not strictly increasing."
            )

    def _require_turn(
        self,
        session_id: str,
        turn_id: str,
    ) -> _RuntimeTurn:
        turn = self._turns.get(session_id)

        if turn is None:
            raise TTSRuntimeError(
                "No active TTS turn exists for this session."
            )

        if turn.request.turn_id != turn_id:
            raise TTSRuntimeError(
                "The supplied turn id does not match the active TTS turn."
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

    @staticmethod
    async def _safe_close(
        stream: TTSStream,
    ) -> None:
        try:
            await stream.close()
        except Exception:
            pass

    @staticmethod
    def _drain_queue(
        queue: asyncio.Queue[
            TTSAudioEvent | Exception | None
        ],
    ) -> None:
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return
