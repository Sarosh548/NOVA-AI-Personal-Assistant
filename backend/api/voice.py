from __future__ import annotations

import asyncio
import json
import time

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
    WebSocketException,
    status,
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
    get_security_settings,
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
) -> str | None:
    authorization = websocket.headers.get(
        "authorization"
    )

    if not authorization:
        return None

    scheme, separator, credentials = (
        authorization.partition(" ")
    )

    if (
        separator != " "
        or scheme.lower() != "bearer"
        or not credentials.strip()
    ):
        return None

    return credentials.strip()


def _validate_origin(
    websocket: WebSocket,
) -> None:
    origin = websocket.headers.get(
        "origin"
    )

    if origin is None:
        return

    allowed_origins = (
        get_security_settings()
        .cors_allowed_origins()
    )

    if (
        not allowed_origins
        or origin not in allowed_origins
    ):
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION
        )


def _resolve_authenticated_context(
    token: str,
):
    if not token.strip():
        raise ValueError(
            "Authentication required."
        )

    # Reuse NOVA's existing authenticated HTTP
    # boundary rather than duplicating JWT/session logic.
    return get_current_auth_context(
        token=token,
        token_service=TokenService(),
        auth_service=AuthService(),
        user_service=UserService(),
        response=None,
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


async def _authenticate_after_connect(
    websocket: WebSocket,
    voice_settings,
):
    try:
        message = await asyncio.wait_for(
            websocket.receive(),
            timeout=(
                voice_settings
                .voice_authentication_timeout_seconds
            ),
        )
    except asyncio.TimeoutError:
        await _send_error(
            websocket,
            code="authentication_timeout",
            message="Authentication was not completed in time.",
        )
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION
        )
        return None

    if message.get("type") != "websocket.receive":
        return None

    text_data = message.get("text")

    if text_data is None:
        await _send_error(
            websocket,
            code="authentication_required",
            message="Authentication required.",
        )
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION
        )
        return None

    if (
        len(
            text_data.encode(
                "utf-8"
            )
        )
        > voice_settings.voice_control_message_max_bytes
    ):
        await websocket.close(
            code=status.WS_1009_MESSAGE_TOO_BIG
        )
        return None

    try:
        control = VoiceControlMessage.model_validate(
            json.loads(
                text_data
            )
        )
    except (
        json.JSONDecodeError,
        ValidationError,
    ):
        await _send_error(
            websocket,
            code="invalid_control_message",
            message="Invalid voice control message.",
        )
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION
        )
        return None

    if (
        control.type
        != "session.authenticate"
        or not control.access_token
        or control.turn_id is not None
    ):
        await _send_error(
            websocket,
            code="authentication_required",
            message="Authentication required.",
        )
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION
        )
        return None

    try:
        return _resolve_authenticated_context(
            control.access_token
        )
    except Exception:
        await _send_error(
            websocket,
            code="authentication_required",
            message="Authentication required.",
        )
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION
        )
        return None


@router.websocket("/ws")
async def voice_websocket(
    websocket: WebSocket,
) -> None:
    voice_settings = get_voice_settings()
    session_service = VoiceSessionService(
        settings=voice_settings
    )
    session = None

    _validate_origin(
        websocket
    )

    header_token = _extract_bearer_token(
        websocket
    )

    await websocket.accept()

    if header_token is not None:
        try:
            context = (
                _resolve_authenticated_context(
                    header_token
                )
            )
        except Exception:
            await _send_error(
                websocket,
                code="authentication_required",
                message="Authentication required.",
            )
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION
            )
            return
    else:
        context = await _authenticate_after_connect(
            websocket,
            voice_settings,
        )

        if context is None:
            return

    try:
        session = (
            session_service.create_session(
                context.user.id
            )
        )

        session_started_monotonic = time.monotonic()

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
            session_elapsed = (
                time.monotonic()
                - session_started_monotonic
            )

            session_remaining = (
                voice_settings
                .voice_session_max_duration_seconds
                - session_elapsed
            )

            if session_remaining <= 0:
                await _send_error(
                    websocket,
                    code="session_max_duration",
                    message=(
                        "Voice session reached the maximum duration."
                    ),
                )
                await websocket.close(
                    code=status.WS_1000_NORMAL_CLOSURE
                )
                return

            receive_timeout = min(
                voice_settings
                .voice_session_idle_timeout_seconds,
                session_remaining,
            )

            try:
                message = await asyncio.wait_for(
                    websocket.receive(),
                    timeout=receive_timeout,
                )
            except asyncio.TimeoutError:
                if session_remaining <= (
                    voice_settings
                    .voice_session_idle_timeout_seconds
                ):
                    await _send_error(
                        websocket,
                        code="session_max_duration",
                        message=(
                            "Voice session reached the maximum duration."
                        ),
                    )
                else:
                    await _send_error(
                        websocket,
                        code="session_idle_timeout",
                        message=(
                            "Voice session closed after "
                            "being idle too long."
                        ),
                    )

                await websocket.close(
                    code=status.WS_1000_NORMAL_CLOSURE
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
                        code=status.WS_1009_MESSAGE_TOO_BIG
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

                if control.type == "session.authenticate":
                    await _send_error(
                        websocket,
                        code="already_authenticated",
                        message=(
                            "Voice session is already authenticated."
                        ),
                    )
                    continue

                if control.access_token is not None:
                    await _send_error(
                        websocket,
                        code="invalid_control_message",
                        message=(
                            "access_token is only valid for "
                            "session.authenticate."
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
                            code=status.WS_1000_NORMAL_CLOSURE
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
                        code=status.WS_1009_MESSAGE_TOO_BIG
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
        if session is not None:
            session_service.close_session(
                session
            )
