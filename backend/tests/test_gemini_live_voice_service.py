from __future__ import annotations

import json

import pytest

from services import gemini_live_voice_service as gemini


def test_gemini_live_config_supports_multilingual_audio_and_nova_tool():
    config = gemini.build_gemini_live_session_config(
        language="multi",
        history=[
            {"role": "user", "content": "I prefer Roman Urdu."},
            {"role": "assistant", "content": "I will mirror your language."},
        ],
    )

    # Validate raw REST BidiGenerateContentSetup casing/nesting, not the
    # flattened convenience config used by the Google SDKs.
    assert config["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert config["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Aoede"
    assert "responseModalities" not in config
    assert "speechConfig" not in config
    assert config["inputAudioTranscription"] == {}
    assert config["outputAudioTranscription"] == {}
    vad = config["realtimeInputConfig"]["automaticActivityDetection"]
    assert vad["disabled"] is False
    assert vad["startOfSpeechSensitivity"] == "START_SENSITIVITY_LOW"
    assert vad["prefixPaddingMs"] == 500
    assert vad["silenceDurationMs"] == 800
    assert "one continuous spoken turn" in config["systemInstruction"]["parts"][0]["text"]
    assert "at most once for each user turn" in config["systemInstruction"]["parts"][0]["text"]
    assert "finalized transcript as the source of truth" in config["systemInstruction"]["parts"][0]["text"]
    assert "Roman Urdu/Hinglish" in config["systemInstruction"]["parts"][0]["text"]
    assert "I prefer Roman Urdu." not in config["systemInstruction"]["parts"][0]["text"]
    assert config["tools"][0]["functionDeclarations"][0]["name"] == "nova_execute_request"


def test_gemini_live_config_keeps_urdu_separate_from_hindi():
    urdu = gemini.build_gemini_live_session_config(language="ur")
    hindi = gemini.build_gemini_live_session_config(language="hi")

    assert "Pakistani Urdu, not Hindi" in urdu["systemInstruction"]["parts"][0]["text"]
    assert "natural Hindi" in hindi["systemInstruction"]["parts"][0]["text"]


@pytest.mark.asyncio
async def test_ephemeral_token_constrains_model_and_allows_client_session_config(monkeypatch):
    captured: dict = {}

    class Response:
        status_code = 200
        is_error = False

        def json(self):
            return {"name": "short-lived-gemini-token"}

    class Client:
        def __init__(self, timeout):
            assert timeout == 20.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, headers, json):
            captured.update(url=url, headers=headers, body=json)
            return Response()

    monkeypatch.setenv("GEMINI_API_KEY", "server-only-google-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(gemini.httpx, "AsyncClient", Client)

    result = await gemini.create_gemini_live_ephemeral_token(
        user_id="user-1",
        language="ur",
        history=[{"role": "user", "content": "Assalam o alaikum"}],
    )

    assert captured["url"] == gemini.GEMINI_TOKEN_URL
    assert captured["headers"]["x-goog-api-key"] == "server-only-google-key"
    assert captured["body"]["uses"] == 1
    assert captured["body"]["fieldMask"] == "model"
    assert captured["body"]["bidiGenerateContentSetup"] == {
        "model": result["model"],
    }
    assert "generationConfig" not in captured["body"]["bidiGenerateContentSetup"]
    assert "liveConnectConstraints" not in captured["body"]
    assert result["token"] == "short-lived-gemini-token"
    assert result["model"] == "models/gemini-3.8-live"
    assert "server-only-google-key" not in json.dumps(result)
    assert "Pakistani Urdu, not Hindi" in result["config"]["systemInstruction"]["parts"][0]["text"]


@pytest.mark.asyncio
async def test_ephemeral_token_requires_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with pytest.raises(gemini.GeminiLiveVoiceNotConfigured):
        await gemini.create_gemini_live_ephemeral_token(user_id="user-1")


@pytest.mark.asyncio
async def test_ephemeral_token_provider_error_keeps_only_safe_diagnostics(monkeypatch, caplog):
    class Response:
        status_code = 400
        is_error = True

        def json(self):
            return {
                "error": {
                    "status": "INVALID_ARGUMENT",
                    "message": "Invalid JSON payload received. Unknown name 'generationConfig' at 'auth_token.bidi_generate_content_setup': Cannot find field.",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.BadRequest",
                            "fieldViolations": [
                                {
                                    "field": "authToken.bidiGenerateContentSetup.generationConfig",
                                    "description": "private raw config should not be logged",
                                }
                            ],
                        }
                    ],
                }
            }

    class Client:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setenv("GEMINI_API_KEY", "server-only-google-key")
    monkeypatch.setattr(gemini.httpx, "AsyncClient", Client)

    with pytest.raises(gemini.GeminiLiveVoiceProviderError) as caught:
        await gemini.create_gemini_live_ephemeral_token(user_id="user-1")

    assert caught.value.status_code == 400
    assert caught.value.provider_code == "INVALID_ARGUMENT"
    assert "Invalid JSON payload received" not in caplog.text
    assert "Cannot find field" not in caplog.text
    assert "private raw config" not in caplog.text
    assert "authToken.bidiGenerateContentSetup.generationConfig" in caplog.text
    assert "unknown_field:generationConfig" in caplog.text
    assert "request_path:auth_token.bidi_generate_content_setup" in caplog.text
    assert "server-only-google-key" not in caplog.text
