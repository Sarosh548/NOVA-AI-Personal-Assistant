from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from urllib.parse import urlencode

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from config import (
    STTProviderSettings,
    get_stt_provider_settings,
)
from services.stt_adapter import (
    STTAdapter,
    STTAdapterError,
    STTAudioFormat,
    STTSpeechStartedEvent,
    STTStream,
    STTStreamClosedError,
    STTStreamNotActiveError,
    STTStreamRequest,
    STTStreamEvent,
    STTTranscriptEvent,
    STTUtteranceEndEvent,
    utc_now,
)


_DEEPGRAM_ENCODING_ALIASES: dict[str, str] = {
    "pcm_s16le": "linear16",
    "linear16": "linear16",
    "mulaw": "mulaw",
    "alaw": "alaw",
    "opus": "opus",
}


class DeepgramSTTStream(STTStream):
    """
    Concrete Deepgram implementation of NOVA's streaming STT contract.

    One instance owns exactly one provider WebSocket connection and exactly
    one NOVA voice turn. Provider messages are converted into the
    provider-neutral STTTranscriptEvent model.
    """

    def __init__(
        self,
        *,
        websocket,
        request: STTStreamRequest,
        settings: STTProviderSettings,
    ):
        self._websocket = websocket
        self._request = request
        self._settings = settings
        self._events: asyncio.Queue[
            STTTranscriptEvent | Exception | None
        ] = asyncio.Queue(
            maxsize=settings.stt_event_queue_max_items
        )
        self._send_lock = asyncio.Lock()
        self._receiver_task: asyncio.Task[None] = asyncio.create_task(
            self._receive_provider_events()
        )
        self._sequence = 0
        self._finished = False
        self._cancelled = False
        self._closed = False

    @property
    def stream_id(self) -> str:
        provider_id = getattr(
            self._websocket,
            "id",
            None,
        )

        if provider_id is not None:
            return str(provider_id)

        return f"deepgram:{self._request.session_id}:{self._request.turn_id}"

    @property
    def turn_id(self) -> str:
        return self._request.turn_id

    async def send_audio(
        self,
        frame: bytes,
    ) -> None:
        if self._closed:
            raise STTStreamClosedError(
                "Deepgram STT stream is closed."
            )

        if self._finished or self._cancelled:
            raise STTStreamNotActiveError(
                "Deepgram STT stream is no longer accepting audio."
            )

        if not isinstance(frame, bytes):
            raise ValueError(
                "Audio frame must be binary data."
            )

        if not frame:
            raise ValueError(
                "Audio frame cannot be empty."
            )

        async with self._send_lock:
            try:
                await self._websocket.send(
                    frame
                )
            except ConnectionClosed as exc:
                raise STTAdapterError(
                    "Deepgram STT connection closed while sending audio."
                ) from exc

    async def events(
        self,
    ) -> AsyncIterator[STTStreamEvent]:
        while True:
            item = await self._events.get()

            if item is None:
                return

            if isinstance(
                item,
                Exception,
            ):
                if isinstance(
                    item,
                    STTAdapterError,
                ):
                    raise item

                raise STTAdapterError(
                    "Deepgram STT event stream failed."
                ) from item

            yield item

    async def finish(self) -> None:
        if self._closed:
            raise STTStreamClosedError(
                "Deepgram STT stream is closed."
            )

        if self._cancelled:
            raise STTStreamNotActiveError(
                "Cancelled Deepgram STT stream cannot be finished."
            )

        if self._finished:
            return

        async with self._send_lock:
            try:
                await self._websocket.send(
                    json.dumps(
                        {
                            "type": "Finalize"
                        }
                    )
                )
            except ConnectionClosed as exc:
                raise STTAdapterError(
                    "Deepgram STT connection closed before finalization."
                ) from exc

        self._finished = True

    async def cancel(self) -> None:
        if self._closed:
            return

        self._cancelled = True

        await self._stop_receiver()
        await self._safe_close_provider()

        self._drain_events()

    async def close(self) -> None:
        if self._closed:
            return

        self._closed = True

        await self._stop_receiver()
        await self._safe_close_provider()

        self._drain_events()

    async def _receive_provider_events(self) -> None:
        try:
            async for raw_message in self._websocket:
                if isinstance(
                    raw_message,
                    bytes,
                ):
                    continue

                if len(
                    raw_message.encode(
                        "utf-8"
                    )
                ) > self._settings.stt_provider_max_message_bytes:
                    await self._events.put(
                        STTAdapterError(
                            "Deepgram STT provider message exceeded "
                            "the configured size limit."
                        )
                    )
                    return

                try:
                    payload = json.loads(
                        raw_message
                    )
                except json.JSONDecodeError as exc:
                    await self._events.put(
                        STTAdapterError(
                            "Deepgram STT provider returned invalid JSON."
                        )
                    )
                    raise exc

                message_type = payload.get(
                    "type"
                )

                if message_type == "Results":
                    event = self._parse_results(
                        payload
                    )

                    if event is not None:
                        await self._events.put(
                            event
                        )

                    continue

                if message_type == "SpeechStarted":
                    self._sequence += 1
                    timestamp = payload.get("timestamp")
                    timestamp_seconds = (
                        float(timestamp)
                        if isinstance(timestamp, (int, float))
                        and timestamp >= 0
                        else None
                    )

                    await self._events.put(
                        STTSpeechStartedEvent(
                            stream_id=self.stream_id,
                            turn_id=self.turn_id,
                            sequence=self._sequence,
                            created_at=utc_now(),
                            timestamp_seconds=timestamp_seconds,
                        )
                    )
                    continue

                if message_type == "UtteranceEnd":
                    last_word_end = payload.get("last_word_end")

                    # Deepgram documents -1 as a stale/duplicate boundary.
                    if (
                        not isinstance(last_word_end, (int, float))
                        or last_word_end < 0
                    ):
                        continue

                    self._sequence += 1

                    await self._events.put(
                        STTUtteranceEndEvent(
                            stream_id=self.stream_id,
                            turn_id=self.turn_id,
                            sequence=self._sequence,
                            created_at=utc_now(),
                            last_word_end_seconds=float(last_word_end),
                        )
                    )
                    continue

                if message_type == "Metadata":
                    continue

                if message_type == "Error":
                    message = payload.get(
                        "message"
                    )

                    safe_message = (
                        str(message).strip()
                        if message is not None
                        else "Deepgram STT provider returned an error."
                    )

                    await self._events.put(
                        STTAdapterError(
                            safe_message[:512]
                        )
                    )
                    return

        except asyncio.CancelledError:
            raise
        except ConnectionClosed as exc:
            if not self._cancelled and not self._closed:
                await self._events.put(
                    STTAdapterError(
                        "Deepgram STT connection closed unexpectedly."
                    )
                )
                return
        except WebSocketException as exc:
            if not self._cancelled and not self._closed:
                await self._events.put(
                    STTAdapterError(
                        "Deepgram STT WebSocket failed."
                    )
                )
                return
        except Exception as exc:
            if not self._cancelled and not self._closed:
                await self._events.put(
                    STTAdapterError(
                        "Deepgram STT event processing failed."
                    )
                )
                return
        finally:
            if not self._cancelled and not self._closed:
                await self._events.put(
                    None
                )

    def _parse_results(
        self,
        payload: dict,
    ) -> STTTranscriptEvent | None:
        channel = payload.get(
            "channel"
        )

        if not isinstance(
            channel,
            dict,
        ):
            return None

        alternatives = channel.get(
            "alternatives"
        )

        if not isinstance(
            alternatives,
            list,
        ) or not alternatives:
            return None

        first_alternative = alternatives[0]

        if not isinstance(
            first_alternative,
            dict,
        ):
            return None

        transcript = first_alternative.get(
            "transcript"
        )

        if not isinstance(
            transcript,
            str,
        ):
            return None

        normalized_text = transcript.strip()

        if not normalized_text:
            return None

        self._sequence += 1

        event_type = (
            "final"
            if payload.get("is_final") is True
            else "partial"
        )

        return STTTranscriptEvent(
            stream_id=self.stream_id,
            turn_id=self.turn_id,
            sequence=self._sequence,
            type=event_type,
            text=normalized_text,
            is_end_of_speech=(
                payload.get("speech_final") is True
            ),
            created_at=utc_now(),
        )

    async def _stop_receiver(self) -> None:
        task = self._receiver_task

        if task is None:
            return

        self._receiver_task = None

        if not task.done():
            task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _safe_close_provider(self) -> None:
        try:
            await self._websocket.close(
                timeout=self._settings.stt_close_timeout_seconds
            )
        except TypeError:
            # Compatibility with simple test doubles and older websocket
            # implementations whose close() doesn't accept timeout.
            try:
                await self._websocket.close()
            except Exception:
                pass
        except Exception:
            pass

    def _drain_events(self) -> None:
        while True:
            try:
                self._events.get_nowait()
            except asyncio.QueueEmpty:
                return


class DeepgramSTTAdapter(STTAdapter):
    """Create authenticated streaming Deepgram STT connections."""

    def __init__(
        self,
        settings: STTProviderSettings | None = None,
    ):
        self.settings = (
            settings
            if settings is not None
            else get_stt_provider_settings()
        )

    async def start_stream(
        self,
        request: STTStreamRequest,
    ) -> STTStream:
        api_key = self.settings.deepgram_api_key

        if api_key is None or not api_key.strip():
            raise STTAdapterError(
                "Deepgram STT API key is not configured."
            )

        provider_encoding = (
            _DEEPGRAM_ENCODING_ALIASES.get(
                request.audio_format.encoding
            )
        )

        if provider_encoding is None:
            raise STTAdapterError(
                "Audio encoding is not supported by the Deepgram adapter."
            )

        uri = self._build_uri(
            request.audio_format,
            provider_encoding,
        )

        try:
            websocket = await connect(
                uri,
                additional_headers={
                    "Authorization": (
                        f"Token {api_key.strip()}"
                    )
                },
                compression=None,
                open_timeout=self.settings.stt_connect_timeout_seconds,
                ping_interval=self.settings.stt_ping_interval_seconds,
                ping_timeout=self.settings.stt_ping_timeout_seconds,
                close_timeout=self.settings.stt_close_timeout_seconds,
                max_size=self.settings.stt_provider_max_message_bytes,
                max_queue=(
                    self.settings.stt_provider_max_queue_items
                ),
                write_limit=32 * 1024,
            )
        except asyncio.TimeoutError as exc:
            raise STTAdapterError(
                "Deepgram STT connection timed out."
            ) from exc
        except (
            OSError,
            WebSocketException,
        ) as exc:
            raise STTAdapterError(
                "Deepgram STT connection failed."
            ) from exc
        except Exception as exc:
            raise STTAdapterError(
                "Deepgram STT connection failed."
            ) from exc

        return DeepgramSTTStream(
            websocket=websocket,
            request=request,
            settings=self.settings,
        )

    def _build_uri(
        self,
        audio_format: STTAudioFormat,
        provider_encoding: str,
    ) -> str:
        params = [
            (
                "model",
                self.settings.deepgram_model,
            ),
            (
                "language",
                self.settings.deepgram_language,
            ),
            (
                "encoding",
                provider_encoding,
            ),
            (
                "sample_rate",
                str(audio_format.sample_rate_hz),
            ),
            (
                "channels",
                str(audio_format.channels),
            ),
            (
                "interim_results",
                str(
                    self.settings.deepgram_interim_results
                ).lower(),
            ),
            (
                "smart_format",
                str(
                    self.settings.deepgram_smart_format
                ).lower(),
            ),
            (
                "endpointing",
                str(
                    self.settings.deepgram_endpointing_ms
                ),
            ),
            (
                "utterance_end_ms",
                str(
                    self.settings.deepgram_utterance_end_ms
                ),
            ),
            (
                "vad_events",
                str(
                    self.settings.deepgram_vad_events
                ).lower(),
            ),
            (
                "no_delay",
                str(
                    self.settings.deepgram_no_delay
                ).lower(),
            ),
        ]

        return (
            self.settings.deepgram_ws_url
            + "?"
            + urlencode(params)
        )
