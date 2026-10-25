from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from api.dependencies import CurrentUserId
from services.gemini_live_voice_service import (
    GeminiLiveLanguage,
    GeminiLiveVoiceNotConfigured,
    GeminiLiveVoiceProviderError,
    create_gemini_live_ephemeral_token,
)


router = APIRouter(prefix="/voice/gemini", tags=["realtime voice"])


@router.post("/token")
async def create_gemini_live_token(
    current_user_id: CurrentUserId,
    conversation_id: int = Query(gt=0),
    language: GeminiLiveLanguage = Query(default="multi"),
) -> dict:
    """Mint a constrained, single-use Gemini Live token for the signed-in user."""
    if conversation_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid NOVA conversation is required.",
        )

    try:
        return await create_gemini_live_ephemeral_token(
            user_id=current_user_id,
            language=language,
        )
    except GeminiLiveVoiceNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Gemini Live is not configured. Create a free Gemini API key in "
                "Google AI Studio, set GEMINI_API_KEY in the Windows user environment, "
                "and restart NOVA. No paid plan is required for the free tier."
            ),
        ) from exc
    except GeminiLiveVoiceProviderError as exc:
        if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "Gemini Live free-tier quota or rate limit was reached. Check Google "
                    "AI Studio usage and limits, wait for the quota to reset, then reconnect. "
                    "This does not mean you need to enable billing."
                ),
                headers={"Retry-After": "30"},
            ) from exc
        if exc.status_code in {401, 403}:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "The Gemini API key is invalid or this project cannot access the selected "
                    "Live model. Check the key and model access in Google AI Studio."
                ),
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "NOVA could not prepare a Gemini Live session. Check Google AI Studio status "
                "and API availability; classic NOVA voice remains available as a fallback."
            ),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="NOVA's Gemini Live configuration is invalid.",
        ) from exc
