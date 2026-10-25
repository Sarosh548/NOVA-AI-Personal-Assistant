from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from api.dependencies import CurrentUserId
from services.conversation_service import ConversationService
from services.openai_realtime_voice_service import (
    RealtimeLanguage,
    RealtimeVoiceNotConfigured,
    RealtimeVoiceProviderError,
    create_realtime_sdp_answer,
)


router = APIRouter(
    prefix="/voice/realtime",
    tags=["realtime voice"],
)


@router.post(
    "/session",
    response_class=Response,
    responses={
        200: {"content": {"application/sdp": {}}},
        502: {"description": "Realtime provider session negotiation failed."},
        503: {"description": "Realtime voice is not configured."},
    },
)
async def create_realtime_voice_session(
    request: Request,
    current_user_id: CurrentUserId,
    conversation_id: int = Query(gt=0),
    language: RealtimeLanguage = Query(default="multi"),
) -> Response:
    """Negotiate WebRTC SDP using the server-only OpenAI API key."""
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/sdp":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="WebRTC session setup requires an application/sdp offer.",
        )

    offer_sdp = (await request.body()).decode("utf-8", errors="replace")
    if not offer_sdp.strip() or len(offer_sdp) > 256_000:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The WebRTC session offer is empty or too large.",
        )

    conversation_service = ConversationService()
    history = conversation_service.get_context_history(
        user_id=current_user_id,
        conversation_id=conversation_id,
        max_messages=12,
        max_characters=12_000,
    )

    try:
        answer_sdp = await create_realtime_sdp_answer(
            offer_sdp=offer_sdp,
            user_id=current_user_id,
            language=language,
            history=history,
        )
    except RealtimeVoiceNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "NOVA realtime voice is not configured on the backend. "
                "Set OPENAI_API_KEY in the server environment."
            ),
        ) from exc
    except RealtimeVoiceProviderError as exc:
        quota_codes = {
            "insufficient_quota",
            "credit_balance_exhausted",
            "organization_usage_limit_exceeded",
            "organization_spend_limit_exceeded",
            "project_spend_limit_exceeded",
        }
        if (
            exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS
            and (
                exc.provider_type == "insufficient_quota"
                or exc.provider_code in quota_codes
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "OpenAI API billing or usage quota is exhausted for "
                    "Realtime voice. Check OpenAI Platform Billing and "
                    "Limits, then reconnect. Classic NOVA voice remains "
                    "available as a fallback."
                ),
            ) from exc

        if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            headers = {}
            if exc.retry_after_seconds is not None:
                headers["Retry-After"] = str(exc.retry_after_seconds)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "OpenAI Realtime is temporarily rate-limited. Wait a "
                    "little before reconnecting. If this keeps happening, "
                    "check the API project's model and request limits. "
                    "Classic NOVA voice remains available as a fallback."
                ),
                headers=headers,
            ) from exc

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "NOVA could not establish realtime voice. Check OpenAI API "
                "access and session availability. Classic NOVA voice remains "
                "available as a fallback."
            ),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The WebRTC session offer is invalid.",
        ) from exc

    return Response(
        content=answer_sdp,
        media_type="application/sdp",
    )
