from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass


class VoiceResponseStreamBridgeError(RuntimeError):
    """Raised when the realtime response-delta bridge cannot continue."""


@dataclass(frozen=True, slots=True)
class _BridgeTerminal:
    error_message: str | None = None


class VoiceResponseStreamBridge:
    """
    Bridge synchronous LLM response callbacks into an async voice TTS stream.

    The LLM graph runs in a worker thread while the WebSocket/TTS runtime runs
    on the asyncio event loop. Text deltas are therefore passed through a
    bounded asyncio queue using run_coroutine_threadsafe. A full queue applies
    bounded backpressure so response text is not silently dropped.
    """

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        max_queue_items: int = 64,
        enqueue_timeout_seconds: float = 2.0,
    ):
        if not isinstance(
            loop,
            asyncio.AbstractEventLoop,
        ):
            raise TypeError(
                "loop must be an asyncio event loop."
            )

        if max_queue_items < 1:
            raise ValueError(
                "max_queue_items must be greater than 0."
            )

        if enqueue_timeout_seconds <= 0:
            raise ValueError(
                "enqueue_timeout_seconds must be greater than 0."
            )

        self._loop = loop
        self._queue: asyncio.Queue[
            str | _BridgeTerminal
        ] = asyncio.Queue(
            maxsize=max_queue_items
        )
        self._enqueue_timeout_seconds = (
            float(enqueue_timeout_seconds)
        )
        self._state_lock = threading.Lock()
        self._closed = False
        self._failure_message: str | None = None
        self._terminal_enqueued = False

    def on_delta(
        self,
        delta: str,
    ) -> None:
        """
        Synchronously accept one response delta from the LLM worker thread.

        Whitespace-only chunks are ignored because the TTS boundary rejects
        empty synthesis input.
        """

        if not isinstance(
            delta,
            str,
        ):
            raise VoiceResponseStreamBridgeError(
                "Response delta must be a string."
            )

        if not delta.strip():
            return

        with self._state_lock:
            if self._failure_message is not None:
                raise VoiceResponseStreamBridgeError(
                    self._failure_message
                )

            if self._closed:
                raise VoiceResponseStreamBridgeError(
                    "Response stream bridge is closed."
                )

        if self._loop.is_closed():
            self._mark_failed_from_thread(
                "Response stream event loop is closed."
            )
            raise VoiceResponseStreamBridgeError(
                "Response stream event loop is closed."
            )

        try:
            future = asyncio.run_coroutine_threadsafe(
                self._queue.put(delta),
                self._loop,
            )
        except RuntimeError as exc:
            self._mark_failed_from_thread(
                "Response stream event loop is unavailable."
            )
            raise VoiceResponseStreamBridgeError(
                "Response stream event loop is unavailable."
            ) from exc

        try:
            future.result(
                timeout=self._enqueue_timeout_seconds
            )
        except FutureTimeoutError as exc:
            future.cancel()
            message = (
                "Response stream backpressure deadline was exceeded."
            )
            self._mark_failed_from_thread(
                message
            )
            raise VoiceResponseStreamBridgeError(
                message
            ) from exc
        except Exception as exc:
            message = (
                "Response stream delta delivery failed."
            )
            self._mark_failed_from_thread(
                message
            )
            raise VoiceResponseStreamBridgeError(
                message
            ) from exc

    async def text_deltas(
        self,
    ) -> AsyncIterator[str]:
        """
        Yield response deltas in original order until the bridge is finished.
        """

        while True:
            with self._state_lock:
                failure_message = self._failure_message

            if failure_message is not None:
                self._drain_queue()
                raise VoiceResponseStreamBridgeError(
                    failure_message
                )

            item = await self._queue.get()

            with self._state_lock:
                failure_message = self._failure_message

            if failure_message is not None:
                self._drain_queue()
                raise VoiceResponseStreamBridgeError(
                    failure_message
                )

            if isinstance(
                item,
                _BridgeTerminal,
            ):
                if item.error_message is not None:
                    raise VoiceResponseStreamBridgeError(
                        item.error_message
                    )

                return

            yield item

    async def finish(self) -> None:
        """
        Preserve queued deltas and append a normal terminal marker.
        """

        with self._state_lock:
            if self._closed:
                return

            self._closed = True
            failed = (
                self._failure_message is not None
            )

            if failed or self._terminal_enqueued:
                return

            self._terminal_enqueued = True

        await self._queue.put(
            _BridgeTerminal()
        )

    async def abort(
        self,
        message: str,
    ) -> None:
        """
        Stop delivery and discard queued deltas.

        Used when TTS or the voice session is cancelled so an LLM worker
        callback cannot remain blocked behind a dead consumer.
        """

        normalized_message = str(
            message
        ).strip()

        if not normalized_message:
            normalized_message = (
                "Response stream bridge was aborted."
            )

        with self._state_lock:
            if self._failure_message is None:
                self._failure_message = (
                    normalized_message
                )

            self._closed = True
            enqueue_terminal = not self._terminal_enqueued
            self._terminal_enqueued = True
            failure_message = (
                self._failure_message
                or normalized_message
            )

        self._drain_queue()

        if enqueue_terminal:
            await self._queue.put(
                _BridgeTerminal(
                    error_message=failure_message
                )
            )

    def abort_from_thread(
        self,
        message: str,
    ) -> None:
        """
        Mark the bridge failed without blocking the caller thread.
        """

        normalized_message = str(
            message
        ).strip()

        if not normalized_message:
            normalized_message = (
                "Response stream bridge was aborted."
            )

        with self._state_lock:
            if self._failure_message is not None:
                return

            self._failure_message = (
                normalized_message
            )
            self._closed = True

        if self._loop.is_closed():
            return

        try:
            asyncio.run_coroutine_threadsafe(
                self._abort_on_loop(
                    normalized_message
                ),
                self._loop,
            )
        except RuntimeError:
            return

    async def _abort_on_loop(
        self,
        message: str,
    ) -> None:
        with self._state_lock:
            if self._terminal_enqueued:
                return

            self._terminal_enqueued = True
            failure_message = (
                self._failure_message
                or message
            )

        self._drain_queue()

        await self._queue.put(
            _BridgeTerminal(
                error_message=failure_message
            )
        )

    def _mark_failed_from_thread(
        self,
        message: str,
    ) -> None:
        self.abort_from_thread(
            message
        )

    def _drain_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
