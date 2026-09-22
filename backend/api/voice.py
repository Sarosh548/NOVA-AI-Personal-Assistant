from __future__ import annotations

import asyncio
import json
import time

from fastapi import (
    APIRouter,
    Response,
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
from services.conversation_execution_service import (
    ConversationExecutionService,
)
from services.execution_context import (
    ExecutionContext,
)
from config import (
    get_rate_limit_settings,
    get_security_settings,
    get_tts_provider_settings,
    get_voice_settings,
)
from services.auth_service import (
    AuthService,
)
from services.deepgram_stt_adapter import (
    DeepgramSTTAdapter,
)
from services.rate_limit_service import (
    RateLimitService,
)
from services.stt_adapter import (
    STTAudioFormat,
)
from services.stt_runtime_service import (
    STTRuntimeError,
)
from services.tts_runtime_service import (
    TTSRuntimeError,
)
from services.token_service import (
    TokenService,
)
from services.elevenlabs_tts_adapter import (
    ElevenLabsTTSAdapter,
)
from services.tts_adapter import (
    TTSAudioFormat,
)
from services.voice_tts_orchestrator import (
    VoiceTTSOrchestrator,
    VoiceTTSOrchestratorError,
)
from services.user_service import (
    UserService,
)
from services.voice_response_stream_bridge import (
    VoiceResponseStreamBridge,
    VoiceResponseStreamBridgeError,
)
from services.voice_session_service import (
    VoiceProtocolError,
    VoiceSessionService,
)
from services.voice_stt_orchestrator import (
    VoiceSTTOrchestrator,
    VoiceSTTOrchestratorError,
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
        or control.audio_format is not None
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


def _build_voice_stt_orchestrator(
    voice_settings,
) -> VoiceSTTOrchestrator:
    return VoiceSTTOrchestrator(
        adapter=DeepgramSTTAdapter(),
        settings=voice_settings,
    )


def _build_voice_tts_orchestrator(
    voice_settings,
) -> VoiceTTSOrchestrator:
    return VoiceTTSOrchestrator(
        adapter=ElevenLabsTTSAdapter(),
        settings=voice_settings,
    )


def _tts_audio_format_from_settings(
    voice_settings,
) -> TTSAudioFormat:
    return TTSAudioFormat(
        encoding=voice_settings.voice_tts_output_encoding,
        sample_rate_hz=voice_settings.voice_tts_output_sample_rate_hz,
        channels=voice_settings.voice_tts_output_channels,
    )


async def _relay_tts_audio(
    *,
    websocket: WebSocket,
    orchestrator: VoiceTTSOrchestrator,
) -> None:
    async for event in orchestrator.events():
        if event.type == "audio":
            await websocket.send_bytes(
                event.audio
            )
            continue

        await websocket.send_json(
            {
                "type": "assistant.audio.final",
                "stream_id": event.stream_id,
                "turn_id": event.turn_id,
                "sequence": event.sequence,
                "created_at": event.created_at.isoformat(),
            }
        )


async def _run_tts_output(
    *,
    websocket: WebSocket,
    orchestrator: VoiceTTSOrchestrator,
    response_bridge: VoiceResponseStreamBridge,
) -> None:
    relay_task = asyncio.create_task(
        _relay_tts_audio(
            websocket=websocket,
            orchestrator=orchestrator,
        )
    )

    try:
        async for delta in response_bridge.text_deltas():
            await orchestrator.send_text(
                delta
            )

        await orchestrator.finish_turn()
        await relay_task
    except asyncio.CancelledError:
        try:
            await response_bridge.abort(
                "Voice TTS response stream was cancelled."
            )
        except Exception:
            pass
        raise
    except (
        VoiceResponseStreamBridgeError,
        VoiceTTSOrchestratorError,
        TTSRuntimeError,
        ValueError,
    ) as exc:
        try:
            await response_bridge.abort(
                str(exc)
            )
        except Exception:
            pass

        try:
            await _send_error(
                websocket,
                code="assistant_audio_failed",
                message=str(exc),
            )
        except WebSocketDisconnect:
            pass
    finally:
        if not relay_task.done():
            relay_task.cancel()

            try:
                await relay_task
            except asyncio.CancelledError:
                pass

        try:
            await orchestrator.cancel_turn()
        except Exception:
            pass


async def _cancel_voice_response(
    *,
    assistant_execution_task: asyncio.Task[None] | None,
    tts_task: asyncio.Task[None] | None,
    response_bridge: VoiceResponseStreamBridge | None,
) -> None:
    if response_bridge is not None:
        try:
            await response_bridge.abort(
                "Voice assistant response was interrupted."
            )
        except Exception:
            pass

    if (
        tts_task is not None
        and not tts_task.done()
    ):
        tts_task.cancel()

        try:
            await tts_task
        except asyncio.CancelledError:
            pass

    if (
        assistant_execution_task is not None
        and not assistant_execution_task.done()
    ):
        assistant_execution_task.cancel()

        try:
            await assistant_execution_task
        except asyncio.CancelledError:
            pass


async def _run_voice_assistant_execution(
    *,
    websocket: WebSocket,
    conversation_execution_service: ConversationExecutionService,
    session,
    user_id: str,
    message: str,
    turn_id: str,
    response_bridge: VoiceResponseStreamBridge | None,
    is_execution_current,
) -> None:
    execution_kwargs = {
        "user_id": user_id,
        "message": message,
        "conversation_id": session.conversation_id,
        "execution_context": ExecutionContext.interactive(),
    }

    if response_bridge is not None:
        execution_kwargs["on_response_delta"] = response_bridge.on_delta

    if is_execution_current is not None:
        execution_kwargs["is_execution_current"] = is_execution_current

    try:
        response_payload = await asyncio.to_thread(
            conversation_execution_service.execute_message,
            **execution_kwargs,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        if (
            is_execution_current is not None
            and not is_execution_current()
        ):
            return

        if response_bridge is not None:
            try:
                await response_bridge.abort(
                    "NOVA could not process the voice request."
                )
            except Exception:
                pass

        try:
            await _send_error(
                websocket,
                code="assistant_execution_failed",
                message=(
                    "NOVA could not process the "
                    "voice request."
                ),
            )
        except WebSocketDisconnect:
            pass

        return

    if response_payload.get("cancelled"):
        if response_bridge is not None:
            try:
                await response_bridge.abort(
                    "Voice assistant response was superseded."
                )
            except Exception:
                pass

        return

    if response_payload.get("error"):
        if response_bridge is not None:
            try:
                await response_bridge.abort(
                    str(response_payload["error"])
                )
            except Exception:
                pass

        try:
            await _send_error(
                websocket,
                code="assistant_execution_failed",
                message=str(
                    response_payload["error"]
                ),
            )
        except WebSocketDisconnect:
            pass

        return

    if (
        is_execution_current is not None
        and not is_execution_current()
    ):
        if response_bridge is not None:
            try:
                await response_bridge.abort(
                    "Voice assistant response was superseded."
                )
            except Exception:
                pass
        return

    session.conversation_id = response_payload[
        "conversation_id"
    ]

    try:
        await websocket.send_json(
            {
                "type": "assistant.response",
                "turn_id": turn_id,
                "conversation_id": (
                    session.conversation_id
                ),
                "response": (
                    response_payload["response"]
                ),
                "confirmation": (
                    response_payload.get(
                        "confirmation",
                        {},
                    )
                ),
            }
        )
    except WebSocketDisconnect:
        return

    if response_bridge is not None:
        await response_bridge.finish()


def _get_voice_conversation_execution_service(
    websocket: WebSocket,
) -> ConversationExecutionService | None:
    return getattr(
        websocket.app.state,
        "conversation_execution_service",
        None,
    )


def _audio_format_from_control(
    control: VoiceControlMessage,
    voice_settings,
) -> STTAudioFormat:
    supplied = control.audio_format

    if supplied is None:
        return STTAudioFormat(
            encoding=(
                voice_settings
                .voice_default_audio_encoding
            ),
            sample_rate_hz=(
                voice_settings
                .voice_default_sample_rate_hz
            ),
            channels=(
                voice_settings
                .voice_default_channels
            ),
        )

    return STTAudioFormat(
        encoding=supplied.encoding,
        sample_rate_hz=supplied.sample_rate_hz,
        channels=supplied.channels,
    )


async def _relay_transcripts(
    *,
    websocket: WebSocket,
    orchestrator: VoiceSTTOrchestrator,
    session_service: VoiceSessionService,
    session,
    turn_id: str,
    final_delivery: asyncio.Future[None],
) -> None:
    try:
        async for event in orchestrator.events():
            await websocket.send_json(
                event
            )

            if (
                event.get("type")
                == "transcript.final"
                and not final_delivery.done()
            ):
                final_delivery.set_result(
                    None
                )

    except asyncio.CancelledError:
        raise
    except WebSocketDisconnect:
        return
    except VoiceSTTOrchestratorError as exc:
        try:
            session_service.cancel_turn(
                session=session,
                turn_id=turn_id,
            )
        except VoiceProtocolError:
            pass

        if not final_delivery.done():
            final_delivery.cancel()

        try:
            await _send_error(
                websocket,
                code="stt_error",
                message=str(exc),
            )
        except WebSocketDisconnect:
            pass


@router.websocket("/ws")
async def voice_websocket(
    websocket: WebSocket,
) -> None:
    voice_settings = get_voice_settings()
    session_service = VoiceSessionService(
        settings=voice_settings
    )
    stt_orchestrator: VoiceSTTOrchestrator | None = None
    tts_orchestrator: VoiceTTSOrchestrator | None = None
    transcript_task: asyncio.Task[None] | None = None
    tts_task: asyncio.Task[None] | None = None
    assistant_execution_task: asyncio.Task[None] | None = None
    assistant_response_bridge: VoiceResponseStreamBridge | None = None
    assistant_turn_id: str | None = None
    assistant_response_generation: int | None = None
    final_delivery: asyncio.Future[None] | None = None
    conversation_execution_service = None
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
        stt_orchestrator = _build_voice_stt_orchestrator(
            voice_settings
        )
        tts_orchestrator = _build_voice_tts_orchestrator(
            voice_settings
        )
        conversation_execution_service = (
            _get_voice_conversation_execution_service(
                websocket
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

            if tts_task is not None and tts_task.done():
                try:
                    await tts_task
                except asyncio.CancelledError:
                    pass

                tts_task = None

            if (
                assistant_execution_task is not None
                and assistant_execution_task.done()
            ):
                try:
                    await assistant_execution_task
                except asyncio.CancelledError:
                    pass

                assistant_execution_task = None
                assistant_response_bridge = None
                assistant_turn_id = None
                assistant_response_generation = None

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

                if (
                    control.audio_format is not None
                    and control.type != "turn.start"
                ):
                    await _send_error(
                        websocket,
                        code="invalid_control_message",
                        message=(
                            "audio_format is only valid for "
                            "turn.start."
                        ),
                    )
                    continue

                try:
                    if control.type == "turn.start":
                        had_active_audio = (
                            tts_task is not None
                            and not tts_task.done()
                        )

                        previous_tts_task = tts_task
                        previous_execution_task = (
                            assistant_execution_task
                        )
                        previous_response_bridge = (
                            assistant_response_bridge
                        )

                        tts_task = None
                        assistant_execution_task = None
                        session_service.invalidate_response(
                            session
                        )

                        assistant_response_bridge = None
                        assistant_turn_id = None
                        assistant_response_generation = None

                        await _cancel_voice_response(
                            assistant_execution_task=(
                                previous_execution_task
                            ),
                            tts_task=previous_tts_task,
                            response_bridge=previous_response_bridge,
                        )

                        if had_active_audio:
                            await websocket.send_json(
                                {
                                    "type": "assistant.audio.cancelled",
                                }
                            )

                        if session.active_turn is not None:
                            raise VoiceProtocolError(
                                "turn_already_active",
                                "A voice turn is already active.",
                            )

                        event = session_service.start_turn(
                            session=session,
                            turn_id=control.turn_id,
                        )

                        try:
                            audio_format = _audio_format_from_control(
                                control,
                                voice_settings,
                            )

                            stream_id = (
                                await stt_orchestrator.start_turn(
                                    user_id=context.user.id,
                                    session_id=session.session_id,
                                    turn_id=event["turn_id"],
                                    audio_format=audio_format,
                                )
                            )
                        except (
                            VoiceSTTOrchestratorError,
                            STTRuntimeError,
                            ValueError,
                        ) as exc:
                            session_service.cancel_turn(
                                session=session,
                                turn_id=event["turn_id"],
                            )
                            await _send_error(
                                websocket,
                                code="stt_start_failed",
                                message=str(exc),
                            )
                            continue

                        event["stt_stream_id"] = stream_id

                        await websocket.send_json(
                            event
                        )

                        loop = asyncio.get_running_loop()
                        final_delivery = loop.create_future()

                        transcript_task = asyncio.create_task(
                            _relay_transcripts(
                                websocket=websocket,
                                orchestrator=stt_orchestrator,
                                session_service=session_service,
                                session=session,
                                turn_id=event["turn_id"],
                                final_delivery=final_delivery,
                            )
                        )
                        continue

                    if control.type == "turn.commit":
                        active_turn = session.active_turn

                        if active_turn is None:
                            raise VoiceProtocolError(
                                "no_active_turn",
                                "There is no active voice turn to commit.",
                            )

                        final_event = (
                            await stt_orchestrator.finish_turn()
                        )

                        if final_delivery is not None:
                            await asyncio.wait_for(
                                asyncio.shield(
                                    final_delivery
                                ),
                                timeout=(
                                    voice_settings
                                    .voice_stt_finalization_timeout_seconds
                                ),
                            )

                        event, _audio_data = (
                            session_service.commit_turn(
                                session=session,
                                turn_id=active_turn.turn_id,
                            )
                        )
                        event["transcript"] = final_event.text

                        if transcript_task is not None:
                            transcript_task.cancel()

                            try:
                                await transcript_task
                            except asyncio.CancelledError:
                                pass

                        transcript_task = None
                        final_delivery = None
                        await websocket.send_json(
                            event
                        )

                        turn_id = event["turn_id"]
                        assistant_response_generation = (
                            session_service.begin_response(
                                session,
                                turn_id,
                            )
                        )

                        if conversation_execution_service is None:
                            await _send_error(
                                websocket,
                                code="assistant_execution_unavailable",
                                message=(
                                    "NOVA conversation execution "
                                    "service is unavailable."
                                ),
                            )
                            continue

                        try:
                            session.conversation_id = (
                                await asyncio.to_thread(
                                    conversation_execution_service
                                    .prepare_conversation,
                                    user_id=context.user.id,
                                    conversation_id=(
                                        session.conversation_id
                                    ),
                                )
                            )
                        except Exception:
                            await _send_error(
                                websocket,
                                code="assistant_execution_failed",
                                message=(
                                    "NOVA could not prepare the "
                                    "voice conversation."
                                ),
                            )
                            continue

                        assistant_response_bridge = None

                        if tts_orchestrator is not None:
                            tts_provider_settings = (
                                get_tts_provider_settings()
                            )

                            voice_id = (
                                tts_provider_settings.elevenlabs_voice_id
                            )

                            if (
                                voice_id is not None
                                and voice_id.strip()
                            ):
                                try:
                                    if tts_task is not None:
                                        tts_task.cancel()

                                        try:
                                            await tts_task
                                        except asyncio.CancelledError:
                                            pass

                                    audio_format = (
                                        _tts_audio_format_from_settings(
                                            voice_settings
                                        )
                                    )

                                    stream_id = (
                                        await tts_orchestrator.start_turn(
                                            user_id=context.user.id,
                                            session_id=session.session_id,
                                            turn_id=turn_id,
                                            voice=voice_id,
                                            audio_format=audio_format,
                                        )
                                    )

                                    await websocket.send_json(
                                        {
                                            "type": "assistant.audio.started",
                                            "stream_id": stream_id,
                                            "turn_id": turn_id,
                                            "audio_format": {
                                                "encoding": (
                                                    audio_format.encoding
                                                ),
                                                "sample_rate_hz": (
                                                    audio_format.sample_rate_hz
                                                ),
                                                "channels": (
                                                    audio_format.channels
                                                ),
                                            },
                                        }
                                    )

                                    assistant_response_bridge = (
                                        VoiceResponseStreamBridge(
                                            loop=(
                                                asyncio.get_running_loop()
                                            ),
                                            max_queue_items=(
                                                voice_settings
                                                .voice_response_delta_queue_max_items
                                            ),
                                            enqueue_timeout_seconds=(
                                                voice_settings
                                                .voice_response_delta_enqueue_timeout_seconds
                                            ),
                                        )
                                    )

                                    tts_task = asyncio.create_task(
                                        _run_tts_output(
                                            websocket=websocket,
                                            orchestrator=tts_orchestrator,
                                            response_bridge=(
                                                assistant_response_bridge
                                            ),
                                        )
                                    )
                                except (
                                    VoiceTTSOrchestratorError,
                                    TTSRuntimeError,
                                    ValueError,
                                ) as exc:
                                    assistant_response_bridge = None

                                    await _send_error(
                                        websocket,
                                        code="assistant_audio_start_failed",
                                        message=str(exc),
                                    )

                        assistant_execution_task = (
                            asyncio.create_task(
                                _run_voice_assistant_execution(
                                    websocket=websocket,
                                    conversation_execution_service=(
                                        conversation_execution_service
                                    ),
                                    session=session,
                                    user_id=context.user.id,
                                    message=final_event.text,
                                    turn_id=turn_id,
                                    response_bridge=(
                                        assistant_response_bridge
                                    ),
                                    is_execution_current=(
                                        lambda response_turn_id=turn_id, response_generation=assistant_response_generation: (
                                            session_service
                                            .is_response_current(
                                                session,
                                                turn_id=response_turn_id,
                                                generation=response_generation,
                                            )
                                        )
                                    ),
                                )
                            )
                        )
                        assistant_turn_id = turn_id

                        continue

                    if control.type == "turn.cancel":
                        active_turn = session.active_turn

                        if active_turn is None:
                            response_turn_id = assistant_turn_id
                            response_active = (
                                (
                                    tts_task is not None
                                    and not tts_task.done()
                                )
                                or (
                                    assistant_execution_task
                                    is not None
                                    and not assistant_execution_task.done()
                                )
                                or assistant_response_bridge is not None
                            )

                            if (
                                not response_active
                                or response_turn_id is None
                            ):
                                raise VoiceProtocolError(
                                    "no_active_turn",
                                    "There is no active voice turn to cancel.",
                                )

                            had_active_audio = (
                                tts_task is not None
                                and not tts_task.done()
                            )

                            previous_tts_task = tts_task
                            previous_execution_task = (
                                assistant_execution_task
                            )
                            previous_response_bridge = (
                                assistant_response_bridge
                            )

                            tts_task = None
                            assistant_execution_task = None
                            session_service.invalidate_response(
                                session
                            )

                            assistant_response_bridge = None
                            assistant_turn_id = None
                            assistant_response_generation = None

                            await _cancel_voice_response(
                                assistant_execution_task=(
                                    previous_execution_task
                                ),
                                tts_task=previous_tts_task,
                                response_bridge=previous_response_bridge,
                            )

                            if had_active_audio:
                                await websocket.send_json(
                                    {
                                        "type": "assistant.audio.cancelled",
                                    }
                                )

                            await websocket.send_json(
                                {
                                    "type": "turn.cancelled",
                                    "turn_id": response_turn_id,
                                }
                            )
                            continue

                        turn_id = active_turn.turn_id

                        await stt_orchestrator.cancel_turn()

                        event = session_service.cancel_turn(
                            session=session,
                            turn_id=turn_id,
                        )

                        final_delivery = None

                        if transcript_task is not None:
                            transcript_task.cancel()

                            try:
                                await transcript_task
                            except asyncio.CancelledError:
                                pass

                        transcript_task = None

                        await websocket.send_json(
                            event
                        )
                        continue

                    if control.type == "session.ping":
                        await websocket.send_json(
                            {
                                "type": "session.pong",
                                "session_id": (
                                    session.session_id
                                ),
                            }
                        )
                        continue

                    if control.type == "session.close":
                        previous_tts_task = tts_task
                        previous_execution_task = (
                            assistant_execution_task
                        )
                        previous_response_bridge = (
                            assistant_response_bridge
                        )

                        session_service.invalidate_response(
                            session
                        )

                        tts_task = None
                        assistant_execution_task = None
                        assistant_response_bridge = None
                        assistant_turn_id = None
                        assistant_response_generation = None

                        await _cancel_voice_response(
                            assistant_execution_task=(
                                previous_execution_task
                            ),
                            tts_task=previous_tts_task,
                            response_bridge=previous_response_bridge,
                        )

                        if tts_orchestrator is not None:
                            try:
                                await tts_orchestrator.close_session()
                            except Exception:
                                pass

                        active_turn = session.active_turn

                        if active_turn is not None:
                            await stt_orchestrator.cancel_turn()
                            session_service.cancel_turn(
                                session=session,
                                turn_id=active_turn.turn_id,
                            )

                        if transcript_task is not None:
                            transcript_task.cancel()

                            try:
                                await transcript_task
                            except asyncio.CancelledError:
                                pass

                            transcript_task = None

                        await stt_orchestrator.close_session()

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

                except (
                    VoiceProtocolError,
                    VoiceSTTOrchestratorError,
                    STTRuntimeError,
                ) as exc:
                    await _send_error(
                        websocket,
                        code=getattr(
                            exc,
                            "code",
                            "stt_error",
                        ),
                        message=getattr(
                            exc,
                            "message",
                            str(exc),
                        ),
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

                if session.active_turn is None:
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

                try:
                    session_service.append_audio_frame(
                        session=session,
                        frame=binary_data,
                    )

                    await stt_orchestrator.send_audio(
                        binary_data
                    )
                except (
                    VoiceProtocolError,
                    VoiceSTTOrchestratorError,
                    STTRuntimeError,
                ) as exc:
                    code = getattr(
                        exc,
                        "code",
                        "stt_error",
                    )
                    message = getattr(
                        exc,
                        "message",
                        str(exc),
                    )

                    try:
                        await stt_orchestrator.cancel_turn()
                    except Exception:
                        pass

                    try:
                        if session.active_turn is not None:
                            session_service.cancel_turn(
                                session=session,
                                turn_id=session.active_turn.turn_id,
                            )
                    except VoiceProtocolError:
                        pass

                    if transcript_task is not None:
                        transcript_task.cancel()

                        try:
                            await transcript_task
                        except asyncio.CancelledError:
                            pass

                        transcript_task = None

                    await _send_error(
                        websocket,
                        code=code,
                        message=message,
                    )

                continue

    except WebSocketDisconnect:
        return

    finally:
        previous_tts_task = tts_task
        previous_execution_task = assistant_execution_task
        previous_response_bridge = assistant_response_bridge

        session_service.invalidate_response(
            session
        )

        tts_task = None
        assistant_execution_task = None
        assistant_response_bridge = None
        assistant_turn_id = None
        assistant_response_generation = None

        await _cancel_voice_response(
            assistant_execution_task=(
                previous_execution_task
            ),
            tts_task=previous_tts_task,
            response_bridge=previous_response_bridge,
        )

        if tts_orchestrator is not None:
            try:
                await tts_orchestrator.close_session()
            except Exception:
                pass

        if transcript_task is not None:
            transcript_task.cancel()

            try:
                await transcript_task
            except asyncio.CancelledError:
                pass

        if stt_orchestrator is not None:
            try:
                await stt_orchestrator.close_session()
            except Exception:
                pass

        if session is not None:
            session_service.close_session(
                session
            )
