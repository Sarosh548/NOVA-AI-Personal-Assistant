from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

import api.livekit_voice as livekit_voice


def test_android_livekit_url_uses_the_api_host_only_for_local_urls():
    assert livekit_voice._resolve_livekit_url_for_client(
        "ws://127.0.0.1:7880",
        client_platform="android",
        request_host="10.0.2.2",
    ) == "ws://10.0.2.2:7880"

    assert livekit_voice._resolve_livekit_url_for_client(
        "ws://localhost:7880",
        client_platform="android",
        request_host="192.168.1.20",
    ) == "ws://192.168.1.20:7880"

    # Configured public voice endpoints and desktop URLs must never be rewritten.
    assert livekit_voice._resolve_livekit_url_for_client(
        "wss://voice.example.com",
        client_platform="android",
        request_host="10.0.2.2",
    ) == "wss://voice.example.com"
    assert livekit_voice._resolve_livekit_url_for_client(
        "ws://127.0.0.1:7880",
        client_platform="desktop",
        request_host="10.0.2.2",
    ) == "ws://127.0.0.1:7880"


def test_local_livekit_development_settings_have_loopback_defaults(monkeypatch):
    monkeypatch.setenv("NOVA_ENV", "development")
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)

    assert livekit_voice._livekit_settings() == (
        "ws://127.0.0.1:7880",
        "devkey",
        "secret",
    )


def test_livekit_cloud_never_gets_development_credentials(monkeypatch):
    monkeypatch.setenv("NOVA_ENV", "production")
    monkeypatch.setenv("LIVEKIT_URL", "wss://voice.example.invalid")
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)

    with pytest.raises(HTTPException) as caught:
        livekit_voice._livekit_settings()

    assert caught.value.status_code == 503
    assert "not configured" in caught.value.detail


def test_livekit_token_requires_conversation_owned_by_user(monkeypatch):
    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _query):
            return None

    monkeypatch.setattr(livekit_voice, "Session", lambda _engine: FakeSession())

    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            livekit_voice.create_livekit_voice_token(
                request=None,
                current_user_id="user-123",
                conversation_id=456,
                language="multi",
            )
        )

    assert caught.value.status_code == 404


def test_livekit_token_binds_room_to_owned_conversation(monkeypatch):
    room_config_values = {}

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _query):
            return 456

    class FakeDispatch:
        def __init__(self, *, agent_name, metadata):
            self.agent_name = agent_name
            self.metadata = metadata

    class FakeRoomConfig:
        def __init__(self, *, agents):
            self.agents = agents
            room_config_values["agents"] = agents

    class FakeToken:
        def __init__(self, *, api_key, api_secret):
            assert api_key
            assert api_secret

        def with_identity(self, identity):
            self.identity = identity
            return self

        def with_name(self, name):
            self.name = name
            return self

        def with_ttl(self, ttl):
            self.ttl = ttl
            return self

        def with_grants(self, grants):
            self.grants = grants
            return self

        def with_room_config(self, room_config):
            self.room_config = room_config
            return self

        def to_jwt(self):
            return "test-signed-room-token"

    class FakeGrants:
        def __init__(self, **grants):
            self.values = grants

    class FakeLeaseDecision:
        acquired = True
        retry_after_seconds = 0

    class FakeLeaseService:
        def acquire(self, *, user_id, session_id):
            room_config_values["lease"] = (user_id, session_id)
            return FakeLeaseDecision()

        def release(self, *, user_id, session_id):
            return True

    monkeypatch.setattr(
        livekit_voice,
        "VoiceSessionLeaseService",
        FakeLeaseService,
    )
    monkeypatch.setenv("NOVA_ENV", "development")
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)
    monkeypatch.setattr(livekit_voice, "Session", lambda _engine: FakeSession())
    monkeypatch.setattr(livekit_voice.api, "AccessToken", FakeToken)
    monkeypatch.setattr(livekit_voice.api, "VideoGrants", FakeGrants)
    monkeypatch.setattr(livekit_voice.api, "RoomAgentDispatch", FakeDispatch)
    monkeypatch.setattr(livekit_voice.api, "RoomConfiguration", FakeRoomConfig)

    result = asyncio.run(
        livekit_voice.create_livekit_voice_token(
                request=None,
            current_user_id="user-123",
            conversation_id=456,
            language="ur",
        )
    )

    dispatch = room_config_values["agents"][0]
    metadata = json.loads(dispatch.metadata)
    assert result["token"] == "test-signed-room-token"
    assert result["server_url"] == "ws://127.0.0.1:7880"
    assert result["conversation_id"] == 456
    assert result["room_name"].startswith("nova-")
    assert dispatch.agent_name == "nova-voice"
    assert metadata == {
        "user_id": "user-123",
        "conversation_id": 456,
        "language": "ur",
        "session_id": result["room_name"],
        "client_platform": "desktop",
    }
    assert room_config_values["lease"] == ("user-123", result["room_name"])


def test_livekit_token_rejects_a_second_active_voice_session(monkeypatch):
    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _query):
            return 456

    class FakeLeaseDecision:
        acquired = False
        retry_after_seconds = 42

    class FakeLeaseService:
        def acquire(self, *, user_id, session_id):
            assert user_id == "user-123"
            assert session_id.startswith("nova-")
            return FakeLeaseDecision()

    monkeypatch.setenv("NOVA_ENV", "development")
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)
    monkeypatch.setattr(livekit_voice, "Session", lambda _engine: FakeSession())
    monkeypatch.setattr(
        livekit_voice,
        "VoiceSessionLeaseService",
        FakeLeaseService,
    )

    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            livekit_voice.create_livekit_voice_token(
                request=None,
                current_user_id="user-123",
                conversation_id=456,
                language="multi",
            )
        )

    assert caught.value.status_code == 409
    assert caught.value.headers["Retry-After"] == "42"
    assert "already active" in caught.value.detail


def test_livekit_lease_heartbeat_is_scoped_to_authenticated_user(monkeypatch):
    calls = []

    class FakeLeaseService:
        def heartbeat(self, *, user_id, session_id):
            calls.append((user_id, session_id))
            return True

    monkeypatch.setattr(
        livekit_voice,
        "VoiceSessionLeaseService",
        FakeLeaseService,
    )

    result = asyncio.run(
        livekit_voice.heartbeat_livekit_voice_lease(
            current_user_id="user-123",
            session_id="nova-session-1",
        )
    )

    assert result == {"renewed": True}
    assert calls == [("user-123", "nova-session-1")]


def test_livekit_lease_release_is_scoped_to_authenticated_user(monkeypatch):
    calls = []

    class FakeLeaseService:
        def release(self, *, user_id, session_id):
            calls.append((user_id, session_id))
            return True

    monkeypatch.setattr(
        livekit_voice,
        "VoiceSessionLeaseService",
        FakeLeaseService,
    )

    result = asyncio.run(
        livekit_voice.release_livekit_voice_lease(
            current_user_id="user-123",
            session_id="nova-session-1",
        )
    )

    assert result == {"released": True}
    assert calls == [("user-123", "nova-session-1")]
