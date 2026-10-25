from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config import TTSProviderSettings
from services.tts_adapter import TTSAudioFormat, TTSStreamRequest
from services.voice_tts_adapter_router import VoiceTTSAdapterRouter


def request(language: str):
    return TTSStreamRequest(
        user_id="user",
        session_id="session",
        turn_id=f"turn-{language}",
        voice="elevenlabs-voice",
        audio_format=TTSAudioFormat(
            encoding="pcm_s16le",
            sample_rate_hz=16_000,
            channels=1,
        ),
        language=language,
    )


@pytest.mark.asyncio
async def test_urdu_uses_azure_only_when_key_and_region_are_configured():
    router = VoiceTTSAdapterRouter(
        TTSProviderSettings(
            azure_speech_key=None,
            azure_speech_region=None,
        )
    )
    azure_result = object()
    elevenlabs_result = object()
    router.azure_speech = SimpleNamespace(
        is_configured=False,
        start_stream=AsyncMock(return_value=azure_result),
    )
    router.elevenlabs = SimpleNamespace(
        start_stream=AsyncMock(return_value=elevenlabs_result),
    )

    result = await router.start_stream(request("ur"))

    assert result is elevenlabs_result
    router.elevenlabs.start_stream.assert_awaited_once()


@pytest.mark.asyncio
async def test_configured_azure_route_is_used_for_urdu():
    router = VoiceTTSAdapterRouter(
        TTSProviderSettings(
            azure_speech_key="configured-test-key",
            azure_speech_region="eastus",
        )
    )
    azure_result = object()
    elevenlabs_result = object()
    router.azure_speech = SimpleNamespace(
        is_configured=True,
        start_stream=AsyncMock(return_value=azure_result),
    )
    router.elevenlabs = SimpleNamespace(
        start_stream=AsyncMock(return_value=elevenlabs_result),
    )

    result = await router.start_stream(request("ur"))

    assert result is azure_result
    router.azure_speech.start_stream.assert_awaited_once()
    router.elevenlabs.start_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_hindi_uses_its_separate_configured_azure_voice_route():
    settings = TTSProviderSettings(
        azure_speech_key="configured-test-key",
        azure_speech_region="eastasia",
        azure_speech_urdu_voice="ur-PK-UzmaNeural",
        azure_speech_hindi_voice="hi-IN-Priya:MAI-Voice-2",
        azure_speech_hindi_rate="0%",
    )
    router = VoiceTTSAdapterRouter(settings)
    azure_result = object()
    elevenlabs_result = object()
    router.azure_speech = SimpleNamespace(
        is_configured=True,
        start_stream=AsyncMock(return_value=azure_result),
    )
    router.elevenlabs = SimpleNamespace(
        start_stream=AsyncMock(return_value=elevenlabs_result),
    )

    result = await router.start_stream(request("hi"))

    assert result is azure_result
    assert router.settings.azure_speech_urdu_voice == "ur-PK-UzmaNeural"
    assert router.settings.azure_speech_hindi_voice == "hi-IN-Priya:MAI-Voice-2"
    router.azure_speech.start_stream.assert_awaited_once()
    router.elevenlabs.start_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_english_stays_on_existing_elevenlabs_stream_even_when_azure_is_configured():
    router = VoiceTTSAdapterRouter(
        TTSProviderSettings(
            azure_speech_key="configured-test-key",
            azure_speech_region="eastus",
        )
    )
    azure_result = object()
    elevenlabs_result = object()
    router.azure_speech = SimpleNamespace(
        is_configured=True,
        start_stream=AsyncMock(return_value=azure_result),
    )
    router.elevenlabs = SimpleNamespace(
        start_stream=AsyncMock(return_value=elevenlabs_result),
    )

    result = await router.start_stream(request("en"))

    assert result is elevenlabs_result
    router.azure_speech.start_stream.assert_not_awaited()
    router.elevenlabs.start_stream.assert_awaited_once()


@pytest.mark.asyncio
async def test_partial_azure_credentials_fail_clearly_instead_of_hiding_misconfiguration():
    from services.tts_adapter import TTSAdapterError

    router = VoiceTTSAdapterRouter(
        TTSProviderSettings(
            azure_speech_key="configured-test-key",
            azure_speech_region=None,
        )
    )
    router.azure_speech = SimpleNamespace(
        is_configured=False,
        start_stream=AsyncMock(),
    )
    router.elevenlabs = SimpleNamespace(
        start_stream=AsyncMock(),
    )

    with pytest.raises(TTSAdapterError, match="AZURE_SPEECH_KEY"):
        await router.start_stream(request("ur"))

    router.azure_speech.start_stream.assert_not_awaited()
    router.elevenlabs.start_stream.assert_not_awaited()
