from config import VoiceSettings


def test_voice_tts_audio_chunk_limit_defaults_to_validated_ceiling():
    settings = VoiceSettings()

    assert settings.voice_tts_audio_chunk_max_bytes == 1_048_576


def test_deepgram_utterance_end_default_is_conversational():
    from config import STTProviderSettings

    settings = STTProviderSettings()

    assert settings.deepgram_utterance_end_ms == 1000


def test_voice_auto_turn_commit_grace_defaults_to_responsive_window():
    from config import VoiceSettings

    settings = VoiceSettings()

    assert settings.voice_auto_turn_commit_grace_seconds == 0.45
