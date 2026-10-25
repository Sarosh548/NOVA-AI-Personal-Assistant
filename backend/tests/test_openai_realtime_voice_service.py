from __future__ import annotations

import hashlib
import json

import pytest

from services import openai_realtime_voice_service as realtime


def test_realtime_session_config_enables_speech_to_speech_and_tool_bridge():
    config = realtime.build_realtime_session_config(
        language="multi",
        history=[
            {"role": "user", "content": "Please remember I prefer Roman Urdu."},
            {"role": "assistant", "content": "I will keep that preference in mind."},
        ],
    )

    assert config["type"] == "realtime"
    assert config["model"] == "gpt-realtime-2.1"
    assert config["output_modalities"] == ["audio"]
    assert config["audio"]["input"]["transcription"]["model"] == "gpt-4o-mini-transcribe"
    assert config["audio"]["input"]["turn_detection"]["type"] == "semantic_vad"
    assert config["audio"]["input"]["turn_detection"]["create_response"] is True
    assert config["audio"]["input"]["turn_detection"]["interrupt_response"] is True
    assert config["audio"]["output"]["voice"] == "marin"
    assert "Roman Urdu" in config["instructions"]
    assert "Please remember I prefer Roman Urdu." in config["instructions"]
    assert config["tools"][0]["name"] == "nova_execute_request"
    assert config["tools"][0]["strict"] is True


def test_realtime_language_instructions_distinguish_urdu_and_hindi():
    urdu = realtime.build_realtime_session_config(language="ur")
    hindi = realtime.build_realtime_session_config(language="hi")

    assert "Pakistani Urdu, not Hindi" in urdu["instructions"]
    assert "natural Hindi" in hindi["instructions"]


@pytest.mark.asyncio
async def test_create_realtime_sdp_answer_keeps_api_key_on_server(monkeypatch):
    captured: dict = {}

    class Response:
        is_error = False
        status_code = 200
        text = "v=0\r\ns=OpenAI Realtime answer\r\n"

    class Client:
        def __init__(self, timeout):
            assert timeout == 25.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, headers, files):
            captured["url"] = url
            captured["headers"] = headers
            captured["files"] = files
            return Response()

    monkeypatch.setenv("OPENAI_API_KEY", "test-server-only-key")
    monkeypatch.setattr(realtime.httpx, "AsyncClient", Client)

    answer = await realtime.create_realtime_sdp_answer(
        offer_sdp="v=0\r\no=browser offer\r\n",
        user_id="internal-user-id",
        language="ur",
        history=[{"role": "user", "content": "Assalam o alaikum"}],
    )

    assert answer.startswith("v=0")
    assert captured["url"] == "https://api.openai.com/v1/realtime/calls"
    assert captured["headers"]["Authorization"] == "Bearer test-server-only-key"
    assert captured["headers"]["OpenAI-Safety-Identifier"] == hashlib.sha256(
        b"nova-user:internal-user-id"
    ).hexdigest()
    assert captured["files"]["sdp"] == (None, "v=0\r\no=browser offer\r\n")
    session = json.loads(captured["files"]["session"][1])
    assert session["audio"]["output"]["voice"] == "marin"
    assert "test-server-only-key" not in answer


@pytest.mark.asyncio
async def test_realtime_sdp_negotiation_requires_server_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(realtime.RealtimeVoiceNotConfigured):
        await realtime.create_realtime_sdp_answer(
            offer_sdp="v=0\r\n",
            user_id="user-1",
        )


@pytest.mark.asyncio
async def test_realtime_provider_error_does_not_leak_provider_body(monkeypatch):
    class Response:
        is_error = True
        status_code = 429
        headers = {"Retry-After": "5"}
        text = "private quota detail and secret-like provider payload"

        def json(self):
            return {
                "error": {
                    "type": "insufficient_quota",
                    "code": "credit_balance_exhausted",
                    "message": self.text,
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

    monkeypatch.setenv("OPENAI_API_KEY", "test-server-only-key")
    monkeypatch.setattr(realtime.httpx, "AsyncClient", Client)

    with pytest.raises(realtime.RealtimeVoiceProviderError) as caught:
        await realtime.create_realtime_sdp_answer(
            offer_sdp="v=0\r\n",
            user_id="user-1",
        )

    assert "private quota detail" not in str(caught.value)
    assert "test-server-only-key" not in str(caught.value)
    assert caught.value.status_code == 429
    assert caught.value.provider_type == "insufficient_quota"
    assert caught.value.provider_code == "credit_balance_exhausted"
    assert caught.value.retry_after_seconds == 5


@pytest.mark.asyncio
async def test_realtime_sdp_rejects_invalid_answer(monkeypatch):
    class Response:
        is_error = False
        status_code = 200
        text = '{"error":"not an SDP answer"}'

    class Client:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setenv("OPENAI_API_KEY", "test-server-only-key")
    monkeypatch.setattr(realtime.httpx, "AsyncClient", Client)

    with pytest.raises(realtime.RealtimeVoiceProviderError):
        await realtime.create_realtime_sdp_answer(
            offer_sdp="v=0\r\n",
            user_id="user-1",
        )


@pytest.mark.asyncio
async def test_realtime_api_maps_quota_429_to_actionable_error(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request

    from api import realtime_voice as route

    class ConversationStub:
        def get_context_history(self, **kwargs):
            return []

    async def fail_session(**kwargs):
        raise realtime.RealtimeVoiceProviderError(
            "Provider rejected session setup.",
            status_code=429,
            provider_type="insufficient_quota",
            provider_code="credit_balance_exhausted",
        )

    monkeypatch.setattr(route, "ConversationService", ConversationStub)
    monkeypatch.setattr(route, "create_realtime_sdp_answer", fail_session)

    async def receive():
        return {
            "type": "http.request",
            "body": b"v=0\r\n",
            "more_body": False,
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/voice/realtime/session",
            "headers": [(b"content-type", b"application/sdp")],
            "query_string": b"",
        },
        receive,
    )

    with pytest.raises(HTTPException) as caught:
        await route.create_realtime_voice_session(
            request=request,
            current_user_id="user-1",
            conversation_id=1,
            language="multi",
        )

    assert caught.value.status_code == 503
    assert "billing or usage quota" in caught.value.detail
    assert "Classic NOVA voice" in caught.value.detail


@pytest.mark.asyncio
async def test_realtime_api_preserves_retry_after_for_rate_limit(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request

    from api import realtime_voice as route

    class ConversationStub:
        def get_context_history(self, **kwargs):
            return []

    async def fail_session(**kwargs):
        raise realtime.RealtimeVoiceProviderError(
            "Provider rejected session setup.",
            status_code=429,
            provider_type="rate_limit_error",
            provider_code="rate_limit_exceeded",
            retry_after_seconds=7,
        )

    monkeypatch.setattr(route, "ConversationService", ConversationStub)
    monkeypatch.setattr(route, "create_realtime_sdp_answer", fail_session)

    async def receive():
        return {
            "type": "http.request",
            "body": b"v=0\r\n",
            "more_body": False,
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/voice/realtime/session",
            "headers": [(b"content-type", b"application/sdp")],
            "query_string": b"",
        },
        receive,
    )

    with pytest.raises(HTTPException) as caught:
        await route.create_realtime_voice_session(
            request=request,
            current_user_id="user-1",
            conversation_id=1,
            language="multi",
        )

    assert caught.value.status_code == 429
    assert caught.value.headers["Retry-After"] == "7"
    assert "temporarily rate-limited" in caught.value.detail
