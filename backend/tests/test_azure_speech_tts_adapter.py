import asyncio
from types import SimpleNamespace

import pytest

import services.azure_speech_tts_adapter as provider_module
from config import TTSProviderSettings
from services.azure_speech_tts_adapter import (
    AzureSpeechTTSAdapter,
    AzureSpeechTTSStream,
)
from services.tts_adapter import (
    TTSAudioFormat,
    TTSAdapterError,
    TTSStreamNotActiveError,
    TTSStreamRequest,
)


def make_settings(**overrides):
    values = {
        "azure_speech_key": "test-speech-key",
        "azure_speech_region": "eastus",
        "azure_speech_urdu_voice": "ur-PK-UzmaNeural",
        "azure_speech_urdu_rate": "-20%",
        "azure_speech_hindi_voice": "hi-IN-Priya:MAI-Voice-2",
        "azure_speech_hindi_rate": "0%",
        "tts_connect_timeout_seconds": 3.0,
        "tts_event_queue_max_items": 8,
    }
    values.update(overrides)
    return TTSProviderSettings(**values)


def make_request(**overrides):
    values = {
        "user_id": "user-001",
        "session_id": "session-123",
        "turn_id": "turn-456",
        "voice": "elevenlabs-voice-is-not-used-for-azure",
        "audio_format": TTSAudioFormat(
            encoding="pcm_s16le",
            sample_rate_hz=16_000,
            channels=1,
        ),
        "language": "ur",
    }
    values.update(overrides)
    return TTSStreamRequest(**values)


def install_fake_sdk(monkeypatch, *, audio_chunks=None, reason="completed", error=None):
    state = {
        "audio_chunks": list(audio_chunks if audio_chunks is not None else [b"\x01\x00" * 150]),
        "reason": reason,
        "error": error,
        "ssml": [],
        "speech_configs": [],
        "output_formats": [],
        "synthesis_calls": 0,
    }

    class FakePushAudioOutputStreamCallback:
        def __init__(self):
            pass

    class FakeSpeechConfig:
        def __init__(self, *, subscription, region):
            state["speech_configs"].append(
                {"subscription": subscription, "region": region}
            )

        def set_speech_synthesis_output_format(self, output_format):
            state["output_formats"].append(output_format)

    class FakePushAudioOutputStream:
        def __init__(self, callback):
            self.callback = callback

        def close(self):
            self.callback.close()

    class FakeAudioOutputConfig:
        def __init__(self, *, stream):
            self.stream = stream

    class FakeFuture:
        def __init__(self, synthesizer, ssml):
            self.synthesizer = synthesizer
            self.ssml = ssml

        def get(self):
            state["synthesis_calls"] += 1
            state["ssml"].append(self.ssml)
            if state["error"] is not None:
                raise RuntimeError(str(state["error"]))
            for chunk in state["audio_chunks"]:
                self.synthesizer.audio_config.stream.callback.write(
                    memoryview(chunk)
                )
            return SimpleNamespace(reason=state["reason"])

    class FakeSpeechSynthesizer:
        def __init__(self, *, speech_config, audio_config):
            self.speech_config = speech_config
            self.audio_config = audio_config

        def speak_ssml_async(self, ssml):
            return FakeFuture(self, ssml)

    fake_sdk = SimpleNamespace(
        SpeechConfig=FakeSpeechConfig,
        SpeechSynthesisOutputFormat=SimpleNamespace(
            Raw16Khz16BitMonoPcm="raw-16khz-16bit-mono-pcm"
        ),
        ResultReason=SimpleNamespace(
            SynthesizingAudioCompleted="completed"
        ),
        SpeechSynthesizer=FakeSpeechSynthesizer,
        audio=SimpleNamespace(
            PushAudioOutputStreamCallback=FakePushAudioOutputStreamCallback,
            PushAudioOutputStream=FakePushAudioOutputStream,
            AudioOutputConfig=FakeAudioOutputConfig,
        ),
    )
    monkeypatch.setattr(provider_module, "speechsdk", fake_sdk)
    return state


@pytest.mark.asyncio
async def test_urdu_request_uses_azure_pakistan_voice_and_streams_raw_pcm(
    monkeypatch: pytest.MonkeyPatch,
):
    audio = b"\x01\x00" * 150
    state = install_fake_sdk(
        monkeypatch,
        # Deliberately split between bytes to ensure whole PCM samples survive.
        audio_chunks=[audio[:101], audio[101:]],
    )
    stream = await AzureSpeechTTSAdapter(make_settings()).start_stream(
        make_request()
    )

    collector = asyncio.create_task(_collect_events(stream))
    await stream.send_text("السلام علیکم ")
    await stream.send_text("NOVA <ready> & مدد.")
    await stream.finish()
    events = await collector

    assert state["speech_configs"] == [
        {"subscription": "test-speech-key", "region": "eastus"}
    ]
    assert state["output_formats"] == ["raw-16khz-16bit-mono-pcm"]
    assert '<speak version="1.0" xml:lang="ur-PK">' in state["ssml"][0]
    assert '<voice name="ur-PK-UzmaNeural">' in state["ssml"][0]
    assert '<prosody rate="-20%">' in state["ssml"][0]
    assert "NOVA &lt;ready&gt; &amp; مدد." in state["ssml"][0]
    assert [item.type for item in events] == ["audio", "audio", "final"]
    assert b"".join(item.audio for item in events if item.type == "audio") == audio
    assert events[-1].stream_id.startswith("azure-speech:")


@pytest.mark.parametrize(
    ("language", "first_sentence", "second_sentence"),
    [
        ("hi", "पहला वाक्य अभी बोलो। ", "दूसरा वाक्य।"),
        ("ur", "پہلا جملہ ابھی بول دیں۔ ", "دوسرا جملہ۔"),
    ],
)
@pytest.mark.asyncio
async def test_first_sentence_audio_is_emitted_before_finish(
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    first_sentence: str,
    second_sentence: str,
):
    audio = b"\x10\x00" * 200
    state = install_fake_sdk(monkeypatch, audio_chunks=[audio])
    stream = await AzureSpeechTTSAdapter(make_settings()).start_stream(
        make_request(language=language)
    )
    collector = asyncio.create_task(_collect_events(stream))

    await stream.send_text(first_sentence)
    for _ in range(100):
        if stream._audio_emitted:
            break
        await asyncio.sleep(0.01)

    assert state["synthesis_calls"] == 1
    assert stream._audio_emitted is True
    assert stream._audio_bytes_emitted == len(audio)

    await stream.send_text(second_sentence)
    await stream.finish()
    events = await collector
    audio_events = [event for event in events if event.type == "audio"]
    assert len(audio_events) == 2
    assert [event.type for event in events][-1] == "final"


@pytest.mark.asyncio
async def test_hindi_hd_voice_uses_its_own_locale_and_normal_speed(
    monkeypatch: pytest.MonkeyPatch,
):
    state = install_fake_sdk(monkeypatch, audio_chunks=[b"\x01\x00" * 150])
    stream = await AzureSpeechTTSAdapter(make_settings()).start_stream(
        make_request(language="hi")
    )

    collector = asyncio.create_task(_collect_events(stream))
    await stream.send_text("नमस्ते नोवा, आप कैसे हैं?")
    await stream.finish()
    events = await collector

    assert '<speak version="1.0" xml:lang="hi-IN">' in state["ssml"][0]
    assert '<voice name="hi-IN-Priya:MAI-Voice-2">' in state["ssml"][0]
    assert '<prosody rate="0%">' in state["ssml"][0]
    assert "नमस्ते नोवा, आप कैसे हैं?" in state["ssml"][0]
    assert [event.type for event in events] == ["audio", "final"]


@pytest.mark.asyncio
async def test_hindi_hd_can_speak_urdu_mode_at_normal_speed(
    monkeypatch: pytest.MonkeyPatch,
):
    state = install_fake_sdk(monkeypatch, audio_chunks=[b"\x01\x00" * 150])
    settings = make_settings(
        azure_speech_urdu_voice="hi-IN-Priya:MAI-Voice-2",
        azure_speech_urdu_rate="0%",
        azure_speech_hindi_voice="hi-IN-Priya:MAI-Voice-2",
        azure_speech_hindi_rate="0%",
    )
    stream = await AzureSpeechTTSAdapter(settings).start_stream(
        make_request(language="ur")
    )

    collector = asyncio.create_task(_collect_events(stream))
    await stream.send_text("وعلیکم السلام، آپ کیسے ہیں؟")
    await stream.finish()
    events = await collector

    assert '<speak version="1.0" xml:lang="hi-IN">' in state["ssml"][0]
    assert '<voice name="hi-IN-Priya:MAI-Voice-2">' in state["ssml"][0]
    assert '<prosody rate="0%">' in state["ssml"][0]
    assert "وعلیکم السلام، آپ کیسے ہیں؟" in state["ssml"][0]
    assert [event.type for event in events] == ["audio", "final"]


@pytest.mark.asyncio
async def test_audio_is_split_into_bounded_even_sized_pcm_chunks(
    monkeypatch: pytest.MonkeyPatch,
):
    from services.azure_speech_tts_adapter import _AUDIO_EVENT_CHUNK_BYTES

    audio = b"\x01\x00" * (_AUDIO_EVENT_CHUNK_BYTES + 20)
    install_fake_sdk(monkeypatch, audio_chunks=[audio])
    stream = await AzureSpeechTTSAdapter(make_settings()).start_stream(
        make_request()
    )

    collector = asyncio.create_task(_collect_events(stream))
    await stream.send_text("اردو میں ایک مختصر جواب۔")
    await stream.finish()
    events = await collector

    audio_events = [event for event in events if event.type == "audio"]
    expected_chunks = (len(audio) + _AUDIO_EVENT_CHUNK_BYTES - 1) // _AUDIO_EVENT_CHUNK_BYTES
    assert len(audio_events) == expected_chunks
    assert all(len(event.audio) <= _AUDIO_EVENT_CHUNK_BYTES for event in audio_events)
    assert all(len(event.audio) % 2 == 0 for event in audio_events)
    assert b"".join(event.audio for event in audio_events) == audio
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert events[-1].type == "final"


@pytest.mark.asyncio
async def test_sdk_errors_are_sanitized_and_do_not_expose_provider_details(
    monkeypatch: pytest.MonkeyPatch,
):
    install_fake_sdk(
        monkeypatch,
        error="private-subscription-detail should not be exposed",
    )
    stream = await AzureSpeechTTSAdapter(make_settings()).start_stream(
        make_request(language="hi")
    )
    collector = asyncio.create_task(_collect_events(stream))
    await stream.send_text("नमस्ते नोवा।")

    with pytest.raises(TTSAdapterError, match="Azure Speech synthesis failed") as error:
        await stream.finish()
    with pytest.raises(TTSAdapterError, match="Azure Speech synthesis failed"):
        await collector
    assert "private-subscription-detail" not in str(error.value)


@pytest.mark.asyncio
async def test_empty_sdk_audio_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
):
    install_fake_sdk(monkeypatch, audio_chunks=[])
    stream = await AzureSpeechTTSAdapter(make_settings()).start_stream(
        make_request(language="hi")
    )
    await stream.send_text("नमस्ते नोवा।")

    with pytest.raises(TTSAdapterError, match="empty audio"):
        await stream.finish()


@pytest.mark.asyncio
async def test_missing_credentials_prevent_starting_azure_stream():
    adapter = AzureSpeechTTSAdapter(
        make_settings(azure_speech_key=None, azure_speech_region=None)
    )
    assert adapter.is_configured is False
    with pytest.raises(TTSAdapterError, match="AZURE_SPEECH_KEY"):
        await adapter.start_stream(make_request())


@pytest.mark.asyncio
async def test_stream_enforces_output_format_and_lifecycle():
    stream = AzureSpeechTTSStream(
        request=make_request(
            audio_format=TTSAudioFormat(
                encoding="pcm_s16le",
                sample_rate_hz=24_000,
                channels=1,
            )
        ),
        settings=make_settings(),
    )
    await stream.send_text("یہ ٹیسٹ ہے۔")
    with pytest.raises(TTSAdapterError, match="16 kHz PCM"):
        await stream.finish()

    cancelled = await AzureSpeechTTSAdapter(make_settings()).start_stream(
        make_request()
    )
    await cancelled.cancel()
    with pytest.raises(TTSStreamNotActiveError):
        await cancelled.send_text("اب نہیں")


@pytest.mark.asyncio
async def test_audio_response_size_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(provider_module, "_MAX_PROVIDER_AUDIO_BYTES", 20)
    install_fake_sdk(monkeypatch, audio_chunks=[b"\x00" * 22])
    stream = await AzureSpeechTTSAdapter(make_settings()).start_stream(
        make_request()
    )
    await stream.send_text("بہت مختصر متن۔")

    with pytest.raises(TTSAdapterError, match="size limit"):
        await stream.finish()


async def _collect_events(stream):
    return [event async for event in stream.events()]
