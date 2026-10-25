from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.dependencies import CurrentUserId
from database.connection import engine
from livekit import api
from models.conversation import Conversation
from services.voice_session_lease_service import VoiceSessionLeaseService


router = APIRouter(prefix="/voice/livekit", tags=["livekit voice"])

AGENT_NAME = "nova-voice"
LiveKitLanguage = str


def _livekit_settings() -> tuple[str, str, str]:
    """Return LiveKit connection settings without ever exposing server credentials."""
    environment = os.getenv("NOVA_ENV", "development").strip().lower()
    url = os.getenv("LIVEKIT_URL", "").strip()
    api_key = os.getenv("LIVEKIT_API_KEY", "").strip()
    api_secret = os.getenv("LIVEKIT_API_SECRET", "").strip()

    local_urls = {
        "",
        "ws://127.0.0.1:7880",
        "ws://localhost:7880",
        "http://127.0.0.1:7880",
        "http://localhost:7880",
    }
    is_local_url = not url or url.rstrip("/") in local_urls
    if environment in {"development", "dev", "local", "test"} and is_local_url:
        url = url or "ws://127.0.0.1:7880"
        api_key = api_key or "devkey"
        api_secret = api_secret or "secret"

    if not url or not api_key or not api_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "NOVA's LiveKit WebRTC service is not configured. Start the local "
                "LiveKit server or configure LIVEKIT_URL, LIVEKIT_API_KEY and "
                "LIVEKIT_API_SECRET on the backend."
            ),
        )

    return url, api_key, api_secret


def _resolve_livekit_url_for_client(
    server_url: str,
    *,
    client_platform: str,
    request_host: str | None,
) -> str:
    """Make local LiveKit URLs reachable from the authenticated Android client."""
    if client_platform != "android" or not request_host:
        return server_url
    parsed = urlsplit(server_url)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return server_url
    host_literal = (
        f"[{request_host}]"
        if ":" in request_host and not request_host.startswith("[")
        else request_host
    )
    port_suffix = f":{parsed.port}" if parsed.port else ""
    return urlunsplit(
        (
            parsed.scheme,
            host_literal + port_suffix,
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


@router.post("/token")
async def create_livekit_voice_token(
    current_user_id: CurrentUserId,
    request: Request,
    conversation_id: int = Query(gt=0),
    language: str = Query(default="multi", pattern="^(multi|en-US|ur|hi)$"),
    client_platform: str = "desktop",
) -> dict[str, str | int]:
    """Create a short-lived participant token and dispatch NOVA into its private room."""
    if client_platform not in {"desktop", "android"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported voice client platform.",
        )

    # A caller must own the conversation id used for a voice session.
    with Session(engine) as session:
        owned_conversation_id = session.scalar(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.user_id == current_user_id,
            )
        )

    if owned_conversation_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="NOVA could not find that conversation for the signed-in user.",
        )

    server_url, api_key, api_secret = _livekit_settings()
    server_url = _resolve_livekit_url_for_client(
        server_url,
        client_platform=client_platform,
        request_host=request.url.hostname if request is not None else None,
    )

    room_name = "nova-" + uuid4().hex
    participant_identity = "user-" + uuid4().hex
    lease_service = VoiceSessionLeaseService()

    # Use the existing database-backed lease to ensure two browser tabs or
    # frontend instances cannot dispatch simultaneous LiveKit rooms for one user.
    try:
        lease_decision = await asyncio.to_thread(
            lease_service.acquire,
            user_id=str(current_user_id),
            session_id=room_name,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NOVA could not reserve a voice session. Please retry shortly.",
        ) from exc

    if not lease_decision.acquired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A NOVA voice session is already active in another tab. "
                "End that session before starting a new one."
            ),
            headers={"Retry-After": str(lease_decision.retry_after_seconds)},
        )

    agent_metadata = json.dumps(
        {
            "user_id": current_user_id,
            "conversation_id": conversation_id,
            "language": language,
            "session_id": room_name,
            "client_platform": client_platform,
        },
        separators=(",", ":"),
    )

    try:
        room_config = api.RoomConfiguration(
            agents=[
                api.RoomAgentDispatch(
                    agent_name=AGENT_NAME,
                    metadata=agent_metadata,
                )
            ]
        )
        access_token = (
            api.AccessToken(api_key=api_key, api_secret=api_secret)
            .with_identity(participant_identity)
            .with_name("You")
            .with_ttl(timedelta(minutes=15))
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                )
            )
            .with_room_config(room_config)
            .to_jwt()
        )
    except Exception as exc:
        try:
            await asyncio.to_thread(
                lease_service.release,
                user_id=str(current_user_id),
                session_id=room_name,
            )
        except Exception:
            pass
        # Do not leak credentials, room grants, or token payloads to logs/clients.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NOVA could not prepare a secure LiveKit room token.",
        ) from exc

    return {
        "server_url": server_url,
        "token": access_token,
        "room_name": room_name,
        "conversation_id": conversation_id,
        "participant_identity": participant_identity,
    }


@router.post("/lease/heartbeat")
async def heartbeat_livekit_voice_lease(
    current_user_id: CurrentUserId,
    session_id: str = Query(min_length=1, max_length=100),
) -> dict[str, bool]:
    """Renew only the signed-in user's currently held LiveKit session lease."""
    service = VoiceSessionLeaseService()
    try:
        renewed = await asyncio.to_thread(
            service.heartbeat,
            user_id=str(current_user_id),
            session_id=session_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NOVA could not renew the active voice session.",
        ) from exc
    return {"renewed": renewed}


@router.delete("/lease")
async def release_livekit_voice_lease(
    current_user_id: CurrentUserId,
    session_id: str = Query(min_length=1, max_length=100),
) -> dict[str, bool]:
    """Release a voice lease only when its session ID belongs to this user."""
    service = VoiceSessionLeaseService()
    try:
        released = await asyncio.to_thread(
            service.release,
            user_id=str(current_user_id),
            session_id=session_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NOVA could not release the voice session cleanly.",
        ) from exc
    return {"released": released}
