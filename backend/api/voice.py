from __future__ import annotations

import asyncio
import json

from fastapi import (
    APIRouter,
    HTTPException,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import ValidationError

from api.auth import (
    get_current_auth_context,
)
from api.schemas.voice import (
    VoiceControlMessage,
)
from config import (
    RateLimitSettings,
    get_rate_limit_settings,
    get_voice_settings,
)
from services.auth_service import (
    AuthService,
)
from services.rate_limit_service import (
    RateLimitService,
)
from services.token_service import (
    TokenService,
)
from services.user_service import (
    UserService,
)
from services.voice_session_service import (
    VoiceProtocolError,
    VoiceSessionService,
)


router = APIRouter(
    prefix="/voice",
    tags=["voice"],
)


def _extract_bearer_token(
    websocket: WebSocket,
) -> str:
    authorization = websocket.headers.get(
        "authorization"
    )

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
        )

    scheme, separator, credentials = (
        authorization.partition(" ")
    )

    if (
        separator != " "
        or scheme.lower() != "bearer"
        or not credentials.strip()
    ):
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
        )

    return credentials.strip()


def _resolve_authenticated_context(
    websocket: WebSocket,
):
    token = _extract_bearer_token(
        websocket
    )

    # Reuse NOVA's existing authenticated HTTP
    # boundary rather than duplicating JWT/session logic.
    return get_current_auth_context(
        token=token,
        token_service=TokenService(),
        auth_service=AuthService(),
        user_service=UserService(),
        response=Response(),
        rate_limit_service=RateLimitService(),
        rate_limit_settings=(
            get_rate_limit_settings()
        ),
    )


async def _send_error(
    websocket: WebSocket,
    *,
    code: str,
    message: str,
) -> None:
    await websocket.send_json(
        {
            "type": "error",
            "code": code,
            "message": message,
        }
    )


@router.websocket("/ws")
async def voice_websocket(
    websocket: WebSocket,
) -> None:
    voice_settings = get_voice_settings()

    try:
        context = (
            _resolve_authenticated_context(
                websocket
            )
        )
    except Exception:
        # Do not expose token/session internals
        # over the realtime transport.
        await websocket.accept()

        await _send_error(
            websocket,
            code="authentication_required",
            message="Authentication required.",
        )

        await websocket.close(
            code=1008
        )
        return

    await websocket.accept()

    session_service = VoiceSessionService(
        settings=voice_settings
    )

    try:
        session = (
            session_service.create_session(
                context.user.id
            )
        )

        await websocket.send_json(
            {
                "type": "session.ready",
                "protocol_version": "1",
                "session_id": session.session_id,
                "connected_at": (
                    session.connected_at.isoformat()
                ),
            }
        )

        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive(),
                    timeout=(
                        voice_settings
                        .voice_session_idle_timeout_seconds
                    ),
                )
            except asyncio.TimeoutError:
                await _send_error(
                    websocket,
                    code="session_idle_timeout",
                    message=(
                        "Voice session closed after "
                        "being idle too long."
                    ),
                )

                await websocket.close(
                    code=1000
                )
                return

            message_type = message.get(
                "type"
            )

            if message_type == "websocket.disconnect":
                return

            if message_type != "websocket.receive":
                continue

            text_data = message.get(
                "text"
            )

            if text_data is not None:
                if (
                    len(
                        text_data.encode(
                            "utf-8"
                        )
                    )
                    > voice_settings.voice_control_message_max_bytes
                ):
                    await websocket.close(
                        code=1009
                    )
                    return

                try:
                    control = (
                        VoiceControlMessage.model_validate(
                            json.loads(
                                text_data
                            )
                        )
                    )
                except (
                    json.JSONDecodeError,
                    ValidationError,
                ):
                    await _send_error(
                        websocket,
                        code="invalid_control_message",
                        message=(
                            "Invalid voice control message."
                        ),
                    )
                    continue

                try:
                    if (
                        control.type
                        == "turn.start"
                    ):
                        event = (
                            session_service.start_turn(
                                session=session,
                                turn_id=control.turn_id,
                            )
                        )

                        await websocket.send_json(
                            event
                        )
                        continue

                    if (
                        control.type
                        == "turn.commit"
                    ):
                        event, _audio_data = (
                            session_service.commit_turn(
                                session=session,
                                turn_id=control.turn_id,
                            )
                        )

                        await websocket.send_json(
                            event
                        )
                        continue

                    if (
                        control.type
                        == "turn.cancel"
                    ):
                        event = (
                            session_service.cancel_turn(
                                session=session,
                                turn_id=control.turn_id,
                            )
                        )

                        await websocket.send_json(
                            event
                        )
                        continue

                    if (
                        control.type
                        == "session.ping"
                    ):
                        await websocket.send_json(
                            {
                                "type": "session.pong",
                                "session_id": (
                                    session.session_id
                                ),
                            }
                        )
                        continue

                    if (
                        control.type
                        == "session.close"
                    ):
                        await websocket.send_json(
                            {
                                "type": "session.closed",
                                "session_id": (
                                    session.session_id
                                ),
                            }
                        )

                        await websocket.close(
                            code=1000
                        )
                        return

                except VoiceProtocolError as exc:
                    await _send_error(
                        websocket,
                        code=exc.code,
                        message=exc.message,
                    )

                continue

            binary_data = message.get(
                "bytes"
            )

            if binary_data is not None:
                if len(binary_data) > (
                    voice_settings
                    .voice_audio_frame_max_bytes
                ):
                    await websocket.close(
                        code=1009
                    )
                    return

                try:
                    session_service.append_audio_frame(
                        session=session,
                        frame=binary_data,
                    )
                except VoiceProtocolError as exc:
                    await _send_error(
                        websocket,
                        code=exc.code,
                        message=exc.message,
                    )

                continue

    except WebSocketDisconnect:
        return

    finally:
        session_service.close_session(
            session
        )