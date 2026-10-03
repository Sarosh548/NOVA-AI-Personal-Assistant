from config import VoiceSettings


def test_voice_tts_audio_chunk_limit_defaults_to_validated_ceiling():
    settings = VoiceSettings()

    assert settings.voice_tts_audio_chunk_max_bytes == 1_048_576


def test_deepgram_utterance_end_allows_longer_voice_pauses():
    from config import STTProviderSettings

    settings = STTProviderSettings()

    assert settings.deepgram_utterance_end_ms == 2000


def test_voice_auto_turn_commit_grace_defaults_to_one_second():
    from config import VoiceSettings

    settings = VoiceSettings()

    assert settings.voice_auto_turn_commit_grace_seconds == 1.0
