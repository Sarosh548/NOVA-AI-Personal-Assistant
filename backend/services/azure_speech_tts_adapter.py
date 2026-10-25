from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from xml.sax.saxutils import escape

import azure.cognitiveservices.speech as speechsdk

from config import TTSProviderSettings, get_tts_provider_settings
from services.tts_adapter import (
    DEFAULT_MAX_SYNTHESIS_TEXT_CHARS,
    TTSAudioEvent,
    TTSAdapter,
    TTSAdapterError,
    TTSStream,
    TTSStreamClosedError,
    TTSStreamNotActiveError,
    TTSStreamRequest,
    utc_now,
)

# Bound individual binary events sent to the browser while streaming
# PCM chunks from Azure Speech SDK.
_AUDIO_EVENT_CHUNK_BYTES = 256 * 1024
_MAX_PROVIDER_AUDIO_BYTES = 24 * 1024 * 1024


class AzureSpeechTTSStream(TTSStream):
    """Azure Speech synthesis stream for Hindi and Urdu.

    Completed sentences are queued as the model streams text. Azure Speech
    SDK pushes raw PCM chunks into NOVA's event queue as soon as they arrive,
    so playback can begin while later assistant text is still being generated.
    """

    def __init__(
        self,
        *,
        request: TTSStreamRequest,
        settings: TTSProviderSettings,
    ) -> None:
        self._request = request
        self._settings = settings
        self._text_parts: list[str] = []
        self._text_char_count = 0
        self._pending_text = ""
        self._segments: asyncio.Queue[str | None] = asyncio.Queue()
        self._synthesis_task: asyncio.Task[None] | None = None
        self._events: asyncio.Queue[TTSAudioEvent | Exception | None] = (
            asyncio.Queue(maxsize=settings.tts_event_queue_max_items)
        )
        self._sequence = 0
        self._audio_bytes_emitted = 0
        self._audio_emitted = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._finished = False
        self._cancelled = False
        self._closed = False

    @property
    def stream_id(self) -> str:
        return f"azure-speech:{self._request.session_id}:{self._request.turn_id}"

    @property
    def turn_id(self) -> str:
        return self._request.turn_id

    async def send_text(self, text: str) -> None:
        if self._closed:
            raise TTSStreamClosedError("Azure Speech TTS stream is closed.")
        if self._finished or self._cancelled:
            raise TTSStreamNotActiveError(
                "Azure Speech TTS stream is no longer accepting text."
            )
        if not isinstance(text, str):
            raise ValueError("Synthesis text must be a string.")
        if not text.strip():
            raise ValueError("Synthesis text cannot be empty.")

        self._text_char_count += len(text)
        if self._text_char_count > DEFAULT_MAX_SYNTHESIS_TEXT_CHARS:
            self._text_char_count -= len(text)
            raise ValueError("Synthesis text exceeds the default size limit.")
        self._text_parts.append(text)
        self._pending_text += text

        if self._synthesis_task is None:
            self._loop = asyncio.get_running_loop()
            self._synthesis_task = asyncio.create_task(
                self._run_synthesis_queue(self._loop)
            )
        for segment in self._take_ready_segments():
            await self._segments.put(segment)

    def _take_ready_segments(self) -> list[str]:
        ready: list[str] = []
        while self._pending_text:
            # Start synthesis as soon as the model completes a sentence.
            boundary = re.search(r"[.!?।؟۔](?:\s+|$)", self._pending_text)
            if boundary is not None:
                end = boundary.end()
                segment = self._pending_text[:end].strip()
                self._pending_text = self._pending_text[end:].lstrip()
                if segment:
                    ready.append(segment)
                continue

            # Avoid waiting for a full long answer if it contains no sentence
            # terminator yet; split at a natural word/comma boundary.
            if len(self._pending_text) > 180:
                limit = 160
                candidates = [
                    self._pending_text.rfind(mark, 100, limit)
                    for mark in (" ", ",", ";", "،", "؛")
                ]
                cut = max(candidates)
                if cut >= 100:
                    segment = self._pending_text[: cut + 1].strip()
                    self._pending_text = self._pending_text[cut + 1 :].lstrip()
                    if segment:
                        ready.append(segment)
                    continue
            break
        return ready

    async def _run_synthesis_queue(
        self,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        while True:
            segment = await self._segments.get()
            if segment is None:
                return
            try:
                await asyncio.to_thread(self._synthesize, segment, loop)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Wake the audio-event consumer as well as finish(), so an
                # upstream synthesis error cannot leave a task blocked on get().
                await self._events.put(
                    exc
                    if isinstance(exc, TTSAdapterError)
                    else TTSAdapterError("Azure Speech synthesis failed.")
                )
                raise

    async def events(self) -> AsyncIterator[TTSAudioEvent]:
        while True:
            item = await self._events.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    async def finish(self) -> None:
        if self._closed:
            raise TTSStreamClosedError("Azure Speech TTS stream is closed.")
        if self._cancelled:
            raise TTSStreamNotActiveError(
                "Cancelled Azure Speech TTS stream cannot be finished."
            )
        if self._finished:
            return

        if not "".join(self._text_parts).strip():
            raise ValueError("Synthesis text cannot be empty.")

        self._finished = True
        if self._pending_text.strip():
            await self._segments.put(self._pending_text.strip())
            self._pending_text = ""
        await self._segments.put(None)
        if self._synthesis_task is not None:
            await self._synthesis_task

        if self._audio_bytes_emitted <= 0 or not self._audio_emitted:
            raise TTSAdapterError("Azure Speech returned empty audio.")

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
        await self._events.put(None)

    async def _emit_audio_chunk(self, chunk: bytes) -> None:
        if self._closed or self._cancelled:
            raise TTSStreamNotActiveError(
                "Azure Speech stream ended while audio was being produced."
            )
        if not chunk or len(chunk) % 2:
            raise TTSAdapterError("Azure Speech returned malformed 16-bit PCM audio.")
        if len(chunk) > _AUDIO_EVENT_CHUNK_BYTES:
            raise TTSAdapterError("Azure Speech emitted an oversized audio chunk.")
        if self._audio_bytes_emitted + len(chunk) > _MAX_PROVIDER_AUDIO_BYTES:
            raise TTSAdapterError(
                "Azure Speech audio exceeded the configured response-size limit."
            )

        self._sequence += 1
        await self._events.put(
            TTSAudioEvent(
                stream_id=self.stream_id,
                turn_id=self.turn_id,
                sequence=self._sequence,
                type="audio",
                audio=chunk,
                created_at=utc_now(),
            )
        )
        self._audio_bytes_emitted += len(chunk)
        self._audio_emitted = True

    def _synthesize(
        self,
        text: str,
        loop: asyncio.AbstractEventLoop,
    ) -> int:
        key = (self._settings.azure_speech_key or "").strip()
        region = (self._settings.azure_speech_region or "").strip().lower()
        if not key or not region:
            raise TTSAdapterError(
                "Azure Speech requires AZURE_SPEECH_KEY and AZURE_SPEECH_REGION."
            )
        if not re.fullmatch(r"[a-z0-9-]{2,64}", region):
            raise TTSAdapterError("Azure Speech region is invalid.")

        audio_format = self._request.audio_format
        if (
            audio_format.encoding != "pcm_s16le"
            or audio_format.sample_rate_hz != 16_000
            or audio_format.channels != 1
        ):
            raise TTSAdapterError(
                "Azure Speech requires mono 16 kHz PCM audio."
            )

        use_hindi_voice = self._request.language == "hi"
        voice_setting = (
            self._settings.azure_speech_hindi_voice
            if use_hindi_voice
            else self._settings.azure_speech_urdu_voice
        )
        voice = voice_setting.strip()
        if not re.fullmatch(r"[A-Za-z0-9:-]{3,128}", voice):
            raise TTSAdapterError("Azure Speech voice name is invalid.")

        normalized_voice = voice.lower()
        if (
            normalized_voice.startswith("hi-in-")
            or normalized_voice.startswith("hi-in:")
        ):
            voice_locale = "hi-IN"
        elif normalized_voice.startswith("ur-pk-"):
            voice_locale = "ur-PK"
        elif normalized_voice.startswith("ur-in-"):
            voice_locale = "ur-IN"
        else:
            raise TTSAdapterError(
                "Azure Speech voice locale must be hi-IN, ur-PK, or ur-IN."
            )

        speaking_rate = (
            self._settings.azure_speech_hindi_rate
            if use_hindi_voice
            else self._settings.azure_speech_urdu_rate
        )
        ssml = (
            f'<speak version="1.0" xml:lang="{voice_locale}">'
            f'<voice name="{voice}"><prosody rate="{speaking_rate}">{escape(text)}</prosody></voice>'
            "</speak>"
        )

        stream = self

        class _StreamingAudioCallback(
            speechsdk.audio.PushAudioOutputStreamCallback
        ):
            def __init__(self) -> None:
                super().__init__()
                self.total_bytes = 0
                self.pending_byte = b""
                self.error: TTSAdapterError | None = None

            def write(self, audio_buffer: memoryview) -> int:
                raw = bytes(audio_buffer)
                if not raw:
                    return 0

                self.total_bytes += len(raw)
                if self.total_bytes > _MAX_PROVIDER_AUDIO_BYTES:
                    self.error = TTSAdapterError(
                        "Azure Speech audio exceeded the configured response-size limit."
                    )
                    return len(raw)
                if self.error is not None:
                    return len(raw)

                data = self.pending_byte + raw
                usable_length = len(data) - (len(data) % 2)
                self.pending_byte = data[usable_length:]
                data = data[:usable_length]

                chunk_size = _AUDIO_EVENT_CHUNK_BYTES - (
                    _AUDIO_EVENT_CHUNK_BYTES % 2
                )
                for offset in range(0, len(data), chunk_size):
                    chunk = data[offset : offset + chunk_size]
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            stream._emit_audio_chunk(chunk),
                            loop,
                        )
                        future.result(timeout=60)
                    except Exception:
                        self.error = TTSAdapterError(
                            "Azure Speech audio streaming failed."
                        )
                        break
                return len(raw)

            def close(self) -> None:
                if self.pending_byte and self.error is None:
                    self.error = TTSAdapterError(
                        "Azure Speech returned malformed 16-bit PCM audio."
                    )
                self.pending_byte = b""

        speech_config = speechsdk.SpeechConfig(
            subscription=key,
            region=region,
        )
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm
        )
        callback = _StreamingAudioCallback()
        push_stream = speechsdk.audio.PushAudioOutputStream(callback)
        audio_config = speechsdk.audio.AudioOutputConfig(stream=push_stream)
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )

        try:
            try:
                result = synthesizer.speak_ssml_async(ssml).get()
            except Exception as exc:
                raise TTSAdapterError("Azure Speech synthesis failed.") from exc
        finally:
            try:
                push_stream.close()
            except Exception:
                pass

        if callback.error is not None:
            raise callback.error
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            raise TTSAdapterError("Azure Speech synthesis did not complete.")
        if callback.total_bytes <= 0:
            raise TTSAdapterError("Azure Speech returned empty audio.")
        if callback.total_bytes % 2:
            raise TTSAdapterError(
                "Azure Speech returned malformed 16-bit PCM audio."
            )
        return callback.total_bytes

    async def cancel(self) -> None:
        self._cancelled = True
        self._text_parts.clear()
        self._text_char_count = 0
        self._pending_text = ""
        if self._synthesis_task is not None and not self._synthesis_task.done():
            self._synthesis_task.cancel()
        self._drain_events()

    async def close(self) -> None:
        self._closed = True
        self._text_parts.clear()
        self._text_char_count = 0
        self._pending_text = ""
        if self._synthesis_task is not None and not self._synthesis_task.done():
            self._synthesis_task.cancel()
        self._drain_events()

    def _drain_events(self) -> None:
        while True:
            try:
                self._events.get_nowait()
            except asyncio.QueueEmpty:
                return


class AzureSpeechTTSAdapter(TTSAdapter):
    """Azure Speech adapter for Pakistani Urdu neural voices."""

    def __init__(
        self,
        settings: TTSProviderSettings | None = None,
    ) -> None:
        self.settings = settings if settings is not None else get_tts_provider_settings()

    @property
    def is_configured(self) -> bool:
        return bool(
            (self.settings.azure_speech_key or "").strip()
            and (self.settings.azure_speech_region or "").strip()
        )

    async def start_stream(self, request: TTSStreamRequest) -> TTSStream:
        if not self.is_configured:
            raise TTSAdapterError(
                "Azure Speech requires AZURE_SPEECH_KEY and AZURE_SPEECH_REGION."
            )
        if request.language not in {"ur", "hi"}:
            raise TTSAdapterError(
                "Azure Speech adapter supports explicit Urdu or Hindi requests only."
            )
        return AzureSpeechTTSStream(request=request, settings=self.settings)
