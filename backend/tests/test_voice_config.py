from config import VoiceSettings


def test_voice_tts_audio_chunk_limit_defaults_to_validated_ceiling():
    settings = VoiceSettings()

    assert settings.voice_tts_audio_chunk_max_bytes == 1_048_576
