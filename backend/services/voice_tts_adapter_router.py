from __future__ import annotations

from config import TTSProviderSettings, get_tts_provider_settings
from services.elevenlabs_tts_adapter import ElevenLabsTTSAdapter
from services.tts_adapter import (
    TTSAdapter,
    TTSAdapterError,
    TTSStream,
    TTSStreamRequest,
)


class VoiceTTSAdapterRouter(TTSAdapter):
    """Choose a dedicated Azure Speech voice for Urdu or Hindi when configured.

    English and all other realtime TTS requests retain the existing ElevenLabs
    streaming path. Hindi and Pakistani Urdu remain separate voice routes.
    No provider credentials are exposed to clients.
    """

    def __init__(
        self,
        settings: TTSProviderSettings | None = None,
    ) -> None:
        self.settings = (
            settings if settings is not None else get_tts_provider_settings()
        )
        self.azure_speech = None
        if (
            (self.settings.azure_speech_key or "").strip()
            and (self.settings.azure_speech_region or "").strip()
        ):
            # Azure's SDK is large and optional. Do not import it during cloud API
            # startup when the deployment has not configured this provider.
            from services.azure_speech_tts_adapter import AzureSpeechTTSAdapter

            self.azure_speech = AzureSpeechTTSAdapter(self.settings)
        self.elevenlabs = ElevenLabsTTSAdapter(self.settings)

    async def start_stream(self, request: TTSStreamRequest) -> TTSStream:
        if request.language in {"ur", "hi"}:
            has_key = bool((self.settings.azure_speech_key or "").strip())
            has_region = bool((self.settings.azure_speech_region or "").strip())
            if has_key != has_region:
                raise TTSAdapterError(
                    "Azure Speech configuration is incomplete. Set both "
                    "AZURE_SPEECH_KEY and AZURE_SPEECH_REGION."
                )
            if self.azure_speech.is_configured:
                return await self.azure_speech.start_stream(request)
        return await self.elevenlabs.start_stream(request)
