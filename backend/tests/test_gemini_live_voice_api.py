from __future__ import annotations

import pytest
from fastapi import HTTPException

from api import gemini_live_voice as route
from services.gemini_live_voice_service import (
    GeminiLiveVoiceNotConfigured,
    GeminiLiveVoiceProviderError,
)


@pytest.mark.asyncio
async def test_token_endpoint_explains_free_tier_key_setup(monkeypatch):
    async def not_configured(**kwargs):
        raise GeminiLiveVoiceNotConfigured("internal-only")

    monkeypatch.setattr(route, "create_gemini_live_ephemeral_token", not_configured)

    with pytest.raises(HTTPException) as caught:
        await route.create_gemini_live_token(
            current_user_id="user-1",
            conversation_id=42,
            language="multi",
        )

    assert caught.value.status_code == 503
    assert "Google AI Studio" in caught.value.detail
    assert "GEMINI_API_KEY" in caught.value.detail
    assert "No paid plan is required" in caught.value.detail
    assert "internal-only" not in caught.value.detail


@pytest.mark.asyncio
async def test_token_endpoint_surfaces_free_tier_quota_without_demanding_billing(monkeypatch):
    async def quota(**kwargs):
        raise GeminiLiveVoiceProviderError(
            "provider error",
            status_code=429,
            provider_code="RESOURCE_EXHAUSTED",
        )

    monkeypatch.setattr(route, "create_gemini_live_ephemeral_token", quota)

    with pytest.raises(HTTPException) as caught:
        await route.create_gemini_live_token(
            current_user_id="user-1",
            conversation_id=42,
            language="ur",
        )

    assert caught.value.status_code == 429
    assert "free-tier quota" in caught.value.detail
    assert "does not mean you need to enable billing" in caught.value.detail
