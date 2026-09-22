from __future__ import annotations

import asyncio
import base64
import binascii
import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote, urlencode

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from config import (
    TTSProviderSettings,
    get_tts_provider_settings,
)
from services.tts_adapter import (
    TTSAudioEvent,
    TTSAudioFormat,
    TTSAdapter,
    TTSAdapterError,
    TTSStream,
    TTSStreamClosedError,
    TTSStreamNotActiveError,
    TTSStreamRequest,
    DEFAULT_MAX_SYNTHESIS_TEXT_CHARS,
    utc_now,
)


_ELEVENLABS_PCM_SAMPLE_RATES = {
    16_000,
    22_050,
    24_000,
    44_100,
}


class ElevenLabsTTSStream(TTSStream):
    """
    Concrete ElevenLabs implementation of NOVA's streaming TTS contract.

    One instance owns exactly one provider WebSocket connection and exactly
    one NOVA voice turn. Provider messages are converted into the
    provider-neutral TTSAudioEvent model.
    """

    def __init__(
        self,
        *,
        websocket: Any,
        request: TTSStreamRequest,
        settings: TTSProviderSettings,
    ):
        self._websocket = websocket
        self._request = request
        self._settings = settings
        self._events: asyncio.Queue[
            TTSAudioEvent | Exception | None
        ] = asyncio.Queue(
            maxsize=settings.tts_event_queue_max_items
        )
        self._send_lock = asyncio.Lock()
        self._receiver_task: asyncio.Task[None] | None = (
            asyncio.create_task(
                self._receive_provider_events()
            )
        )
        self._sequence = 0
        self._finished = False
        self._provider_final = False
        self._cancelled = False
        self._closed = False

    @property
    def stream_id(self) -> str:
        return (
            f"elevenlabs:"
            f"{self._request.session_id}:"
            f"{self._request.turn_id}"
        )

    @property
    def turn_id(self) -> str:
        return self._request.turn_id

    async def send_text(
        self,
        text: str,
    ) -> None:
        self._ensure_sendable()

        if not isinstance(text, str):
            raise ValueError(
                "Synthesis text must be a string."
            )

        normalized_text = text.strip()

        if not normalized_text:
            raise ValueError(
                "Synthesis text cannot be empty."
            )

        if len(normalized_text) > DEFAULT_MAX_SYNTHESIS_TEXT_CHARS:
            raise ValueError(
                "Synthesis text exceeds the default size limit."
            )

        payload = {
            "text": normalized_text + " ",
        }

        async with self._send_lock:
            try:
                await self._websocket.send(
                    json.dumps(payload)
                )
            except ConnectionClosed as exc:
                raise TTSAdapterError(
                    "ElevenLabs TTS connection closed while sending text."
                ) from exc

    async def events(
        self,
    ) -> AsyncIterator[TTSAudioEvent]:
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
                    TTSAdapterError,
                ):
                    raise item

                raise TTSAdapterError(
                    "ElevenLabs TTS event stream failed."
                ) from item

            yield item

    async def finish(self) -> None:
        if self._closed:
            raise TTSStreamClosedError(
                "ElevenLabs TTS stream is closed."
            )

        if self._cancelled:
            raise TTSStreamNotActiveError(
                "Cancelled ElevenLabs TTS stream cannot be finished."
            )

        if self._finished:
            return

        async with self._send_lock:
            try:
                await self._websocket.send(
                    json.dumps(
                        {
                            "text": "",
                        }
                    )
                )
            except ConnectionClosed as exc:
                raise TTSAdapterError(
                    "ElevenLabs TTS connection closed before finalization."
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

                raw_size = len(
                    raw_message.encode(
                        "utf-8"
                    )
                )

                if raw_size > self._settings.tts_provider_max_message_bytes:
                    await self._events.put(
                        TTSAdapterError(
                            "ElevenLabs TTS provider message exceeded "
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
                        TTSAdapterError(
                            "ElevenLabs TTS provider returned invalid JSON."
                        )
                    )
                    raise exc

                if not isinstance(
                    payload,
                    dict,
                ):
                    await self._events.put(
                        TTSAdapterError(
                            "ElevenLabs TTS provider returned an invalid message."
                        )
                    )
                    return

                provider_error = (
                    payload.get("error")
                    or payload.get("message")
                )

                if provider_error is not None:
                    safe_message = str(
                        provider_error
                    ).strip()

                    await self._events.put(
                        TTSAdapterError(
                            (
                                safe_message
                                or "ElevenLabs TTS provider returned an error."
                            )[:512]
                        )
                    )
                    return

                audio_value = payload.get(
                    "audio"
                )

                if isinstance(
                    audio_value,
                    str,
                ) and audio_value:
                    try:
                        audio = base64.b64decode(
                            audio_value,
                            validate=True,
                        )
                    except (
                        ValueError,
                        binascii.Error,
                    ) as exc:
                        await self._events.put(
                            TTSAdapterError(
                                "ElevenLabs TTS provider returned invalid audio data."
                            )
                        )
                        raise exc

                    if audio:
                        self._sequence += 1

                        await self._events.put(
                            TTSAudioEvent(
                                stream_id=self.stream_id,
                                turn_id=self.turn_id,
                                sequence=self._sequence,
                                type="audio",
                                audio=audio,
                                created_at=utc_now(),
                            )
                        )

                if (
                    payload.get("is_final") is True
                    or payload.get("isFinal") is True
                ):
                    self._provider_final = True
                    self._sequence += 1

                    await self._events.put(
                        TTSAudioEvent(
                            stream_id=self.stream_id,
                            turn_id=self.turn_id,
                            sequence=self._sequence,
                            type="final",
                            audio=b"",
                            created_at=utc_now(),
                        )
                    )
                    return

        except asyncio.CancelledError:
            raise
        except ConnectionClosed as exc:
            if (
                not self._cancelled
                and not self._closed
                and not self._provider_final
            ):
                await self._events.put(
                    TTSAdapterError(
                        "ElevenLabs TTS connection closed unexpectedly."
                    )
                )
        except WebSocketException as exc:
            if not self._cancelled and not self._closed:
                await self._events.put(
                    TTSAdapterError(
                        "ElevenLabs TTS WebSocket failed."
                    )
                )
        except Exception:
            if not self._cancelled and not self._closed:
                await self._events.put(
                    TTSAdapterError(
                        "ElevenLabs TTS event processing failed."
                    )
                )
        finally:
            if (
                not self._cancelled
                and not self._closed
                and self._provider_final
            ):
                await self._events.put(
                    None
                )

    def _ensure_sendable(self) -> None:
        if self._closed:
            raise TTSStreamClosedError(
                "ElevenLabs TTS stream is closed."
            )

        if self._finished or self._cancelled:
            raise TTSStreamNotActiveError(
                "ElevenLabs TTS stream is no longer accepting text."
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
                timeout=self._settings.tts_close_timeout_seconds
            )
        except TypeError:
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


class ElevenLabsTTSAdapter(TTSAdapter):
    """Create authenticated streaming ElevenLabs TTS connections."""

    def __init__(
        self,
        settings: TTSProviderSettings | None = None,
    ):
        self.settings = (
            settings
            if settings is not None
            else get_tts_provider_settings()
        )

    async def start_stream(
        self,
        request: TTSStreamRequest,
    ) -> TTSStream:
        api_key = self.settings.elevenlabs_api_key

        if api_key is None or not api_key.strip():
            raise TTSAdapterError(
                "ElevenLabs TTS API key is not configured."
            )

        output_format = self._output_format(
            request.audio_format
        )

        uri = self._build_uri(
            request,
            output_format,
        )

        try:
            websocket = await connect(
                uri,
                additional_headers={
                    "xi-api-key": api_key.strip(),
                },
                compression=None,
                open_timeout=self.settings.tts_connect_timeout_seconds,
                ping_interval=self.settings.tts_ping_interval_seconds,
                ping_timeout=self.settings.tts_ping_timeout_seconds,
                close_timeout=self.settings.tts_close_timeout_seconds,
                max_size=self.settings.tts_provider_max_message_bytes,
                max_queue=self.settings.tts_provider_max_queue_items,
                write_limit=32 * 1024,
            )
        except asyncio.TimeoutError as exc:
            raise TTSAdapterError(
                "ElevenLabs TTS connection timed out."
            ) from exc
        except (
            OSError,
            WebSocketException,
        ) as exc:
            raise TTSAdapterError(
                "ElevenLabs TTS connection failed."
            ) from exc
        except Exception as exc:
            raise TTSAdapterError(
                "ElevenLabs TTS connection failed."
            ) from exc

        stream = ElevenLabsTTSStream(
            websocket=websocket,
            request=request,
            settings=self.settings,
        )

        try:
            await websocket.send(
                json.dumps(
                    self._initial_payload()
                )
            )
        except ConnectionClosed as exc:
            await stream.close()
            raise TTSAdapterError(
                "ElevenLabs TTS connection closed during initialization."
            ) from exc
        except Exception as exc:
            await stream.close()
            raise TTSAdapterError(
                "ElevenLabs TTS initialization failed."
            ) from exc

        return stream

    def _build_uri(
        self,
        request: TTSStreamRequest,
        output_format: str,
    ) -> str:
        voice_id = quote(
            request.voice,
            safe="",
        )

        params = {
            "model_id": self.settings.elevenlabs_model,
            "output_format": output_format,
        }

        if request.language is not None:
            params["language_code"] = request.language

        return (
            self.settings.elevenlabs_ws_url.rstrip("/")
            + "/"
            + voice_id
            + "/stream-input?"
            + urlencode(params)
        )

    def _initial_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "text": " ",
            "voice_settings": {
                "stability": self.settings.elevenlabs_stability,
                "similarity_boost": (
                    self.settings.elevenlabs_similarity_boost
                ),
                "speed": self.settings.elevenlabs_speed,
                "use_speaker_boost": (
                    self.settings.elevenlabs_use_speaker_boost
                ),
            },
            "generation_config": {
                "chunk_length_schedule": (
                    self.settings.chunk_length_schedule()
                ),
            },
        }

        return payload

    @staticmethod
    def _output_format(
        audio_format: TTSAudioFormat,
    ) -> str:
        if audio_format.channels != 1:
            raise TTSAdapterError(
                "ElevenLabs TTS output currently requires mono audio."
            )

        encoding = audio_format.encoding

        if (
            encoding == "pcm_s16le"
            and audio_format.sample_rate_hz
            in _ELEVENLABS_PCM_SAMPLE_RATES
        ):
            return (
                f"pcm_{audio_format.sample_rate_hz}"
            )

        if (
            encoding in {"ulaw", "mulaw"}
            and audio_format.sample_rate_hz == 8_000
        ):
            return "ulaw_8000"

        raise TTSAdapterError(
            "Audio format is not supported by the ElevenLabs TTS adapter."
        )
