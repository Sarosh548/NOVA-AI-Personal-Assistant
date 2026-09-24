import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
import time

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    JSONResponse,
    Response,
)
from pydantic import BaseModel

from security import configure_api_security

from agent.graph import build_graph
from api.activity import (
    router as activity_router,
)
from api.auth import router as auth_router
from api.conversations import (
    router as conversations_router,
)
from api.calendar import (
    router as calendar_router,
)
from api.memories import (
    router as memories_router,
)
from api.health import (
    router as health_router,
)
from api.dependencies import (
    CurrentUserId,
    authorize_user_scope,
)
from api.knowledge import (
    router as knowledge_router,
)
from api.notification_destinations import (
    router as notification_destinations_router,
)
from api.permissions import (
    router as permissions_router,
)
from api.reminders import (
    router as reminders_router,
)
from api.tasks import (
    router as tasks_router,
)
from api.workflows import (
    router as workflows_router,
)
from api.confirmations import (
    router as confirmations_router,
)
from api.voice import (
    router as voice_router,
)
from services.autonomous_workflow_scheduler import (
    AutonomousWorkflowScheduler,
)
from services.conversation_service import (
    ConversationService,
)
from services.conversation_execution_service import (
    ConversationExecutionService,
)
from services.execution_context import (
    ExecutionContext,
)
from services.execution_service import (
    NOVAExecutionService,
)
from services.idempotency_cleanup_scheduler import (
    IdempotencyCleanupScheduler,
)
from services.idempotency_service import (
    IdempotencyService,
)
from services.llm_service import LLMService
from services.memory_service import MemoryService
from services.notification_destination_service import (
    NotificationDestinationService,
)
from services.notification_factory import (
    build_notification_service,
)
from services.notification_service import (
    NotificationService,
)
from services.notification_delivery_cleanup_scheduler import (
    NotificationDeliveryCleanupScheduler,
)
from services.request_context import (
    normalize_request_id,
    reset_request_id,
    set_request_id,
)
from services.api_observability import (
    configure_api_logging,
    log_api_exception,
    log_api_request,
)
from services.api_metrics import (
    api_metrics,
    generate_metrics,
)
from services.proactive_activity_notification_service import (
    ProactiveActivityNotificationService,
)
from services.proactive_activity_scheduler import (
    ProactiveActivityScheduler,
)
from services.production_config_service import (
    validate_runtime_configuration,
)
from services.reminder_scheduler import (
    ReminderScheduler,
)
from services.reminder_service import (
    ReminderService,
)
from services.user_notification_preferences_service import (
    UserNotificationPreferencesService,
)


@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    await startup_event()

    try:
        yield
    finally:
        await shutdown_event()


app = FastAPI(
    lifespan=lifespan
)

configure_api_security(app)


@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request,
    exc: HTTPException,
):
    response = JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": jsonable_encoder(
                exc.detail
            )
        },
        headers=exc.headers,
    )

    request_id = getattr(
        request.state,
        "request_id",
        None,
    )

    if request_id:
        response.headers["X-Request-ID"] = request_id

    return response


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    response = JSONResponse(
        status_code=422,
        content={
            "detail": jsonable_encoder(
                exc.errors()
            )
        },
    )

    request_id = getattr(
        request.state,
        "request_id",
        None,
    )

    if request_id:
        response.headers["X-Request-ID"] = request_id

    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
):
    response = JSONResponse(
        status_code=500,
        content={
            "detail": "Internal Server Error"
        },
    )

    request_id = getattr(
        request.state,
        "request_id",
        None,
    )

    if request_id:
        response.headers["X-Request-ID"] = request_id

    return response


app.include_router(auth_router)
app.include_router(health_router)
app.include_router(conversations_router)
app.include_router(calendar_router)
app.include_router(memories_router)
app.include_router(tasks_router)
app.include_router(reminders_router)
app.include_router(activity_router)
app.include_router(workflows_router)
app.include_router(confirmations_router)
app.include_router(knowledge_router)
app.include_router(
    notification_destinations_router
)
app.include_router(
    permissions_router
)
app.include_router(
    voice_router
)

llm_service = LLMService()

memory_service = MemoryService(
    llm_service
)

conversation_service = ConversationService()

agent_graph = build_graph()

execution_service = NOVAExecutionService(
    agent_graph
)

reminder_service = ReminderService()

# Safe import-time fallback.
#
# Runtime provider configuration is loaded during FastAPI startup.
notification_service: NotificationService = (
    NotificationService()
)

notification_destination_service = (
    NotificationDestinationService()
)

reminder_scheduler = ReminderScheduler(
    interval_seconds=5,
    reminder_service=reminder_service,
    notification_service=notification_service,
    batch_size=50,
)

autonomous_workflow_scheduler = (
    AutonomousWorkflowScheduler(
        interval_seconds=5,
        notification_service=notification_service,
    )
)

proactive_activity_notification_service = (
    ProactiveActivityNotificationService(
        notification_service=notification_service,
    )
)

proactive_activity_scheduler = ProactiveActivityScheduler(
    interval_seconds=5,
    notification_service=(
        proactive_activity_notification_service
    ),
)

user_notification_preferences_service = (
    UserNotificationPreferencesService()
)

idempotency_service = IdempotencyService()

idempotency_cleanup_scheduler = (
    IdempotencyCleanupScheduler(
        interval_seconds=300,
        idempotency_service=idempotency_service,
        batch_size=500,
    )
)

notification_delivery_cleanup_scheduler = (
    NotificationDeliveryCleanupScheduler(
        interval_seconds=300,
        retention_seconds=30 * 24 * 60 * 60,
        batch_size=500,
    )
)

scheduler_task: asyncio.Task | None = None

idempotency_cleanup_scheduler_task: (
    asyncio.Task | None
) = None

notification_delivery_cleanup_scheduler_task: (
    asyncio.Task | None
) = None

autonomous_workflow_scheduler_task: (
    asyncio.Task | None
) = None

proactive_activity_scheduler_task: (
    asyncio.Task | None
) = None

CONTEXT_MAX_MESSAGES = 12
CONTEXT_MAX_CHARACTERS = 12000

conversation_execution_service = ConversationExecutionService(
    conversation_service=conversation_service,
    execution_service=execution_service,
    llm_service=llm_service,
    memory_service=memory_service,
    context_max_messages=CONTEXT_MAX_MESSAGES,
    context_max_characters=CONTEXT_MAX_CHARACTERS,
)

app.state.conversation_execution_service = (
    conversation_execution_service
)


class ChatRequest(BaseModel):
    message: str
    conversation_id: int | None = None


class NotificationPreferencesUpdateRequest(BaseModel):
    timezone: str | None = None
    daily_activity_digest_enabled: bool | None = None
    delivery_hour: int | None = None
    delivery_minute: int | None = None


class NotificationPreferencesResponse(BaseModel):
    id: int
    user_id: str
    timezone: str
    daily_activity_digest_enabled: bool
    delivery_hour: int
    delivery_minute: int
    created_at: datetime
    updated_at: datetime


def _notification_preferences_payload(
    preferences,
) -> dict:
    return {
        "id": preferences.id,
        "user_id": preferences.user_id,
        "timezone": preferences.timezone,
        "daily_activity_digest_enabled": (
            preferences.daily_activity_digest_enabled
        ),
        "delivery_hour": preferences.delivery_hour,
        "delivery_minute": preferences.delivery_minute,
        "created_at": preferences.created_at,
        "updated_at": preferences.updated_at,
    }


def _request_route_template(
    request: Request,
) -> str:
    route = request.scope.get(
        "route"
    )

    route_path = getattr(
        route,
        "path",
        None,
    )

    if isinstance(route_path, str) and route_path:
        return route_path

    return "__unmatched__"


@app.middleware("http")
async def request_id_middleware(
    request: Request,
    call_next,
):
    incoming_request_id = request.headers.get(
        "X-Request-ID"
    )

    request_id = normalize_request_id(
        incoming_request_id
    )

    request.state.request_id = request_id
    token = set_request_id(
        request_id
    )

    started_at = time.perf_counter()
    api_metrics.start_request()

    try:
        response = await call_next(
            request
        )
    except Exception:
        duration_ms = (
            time.perf_counter()
            - started_at
        ) * 1000

        api_metrics.observe_request(
            method=request.method,
            route=_request_route_template(
                request
            ),
            status_code=500,
            duration_seconds=(
                duration_ms
                / 1000
            ),
        )

        log_api_exception(
            request_id=request_id,
            method=request.method,
            route=_request_route_template(
                request
            ),
            duration_ms=duration_ms,
        )
        raise
    else:
        duration_ms = (
            time.perf_counter()
            - started_at
        ) * 1000

        api_metrics.observe_request(
            method=request.method,
            route=_request_route_template(
                request
            ),
            status_code=response.status_code,
            duration_seconds=(
                duration_ms
                / 1000
            ),
        )

        log_api_request(
            request_id=request_id,
            method=request.method,
            route=_request_route_template(
                request
            ),
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
    finally:
        api_metrics.end_request()
        reset_request_id(
            token
        )

    response.headers["X-Request-ID"] = request_id
    return response


async def startup_event():
    configure_api_logging()

    validate_runtime_configuration()

    global scheduler_task
    global idempotency_cleanup_scheduler_task
    global notification_delivery_cleanup_scheduler_task
    global autonomous_workflow_scheduler_task
    global proactive_activity_scheduler_task
    global notification_service

    notification_service = (
        build_notification_service(
            destination_service=(
                notification_destination_service
            )
        )
    )

    # The agent graph and its confirmation executor share the same
    # ToolRouter instance. Inject the runtime-configured provider so
    # confirmed email actions use the exact startup configuration.
    from agent import graph as agent_graph_module

    agent_graph_module.tool_router.notification_service = (
        notification_service
    )

    reminder_scheduler.notification_service = (
        notification_service
    )

    autonomous_workflow_scheduler.notification_service = (
        notification_service
    )

    proactive_activity_notification_service.notification_service = (
        notification_service
    )

    if (
        scheduler_task is None
        or scheduler_task.done()
    ):
        scheduler_task = asyncio.create_task(
            reminder_scheduler.run()
        )

    if (
        idempotency_cleanup_scheduler_task is None
        or idempotency_cleanup_scheduler_task.done()
    ):
        idempotency_cleanup_scheduler_task = (
            asyncio.create_task(
                idempotency_cleanup_scheduler.run()
            )
        )

    if (
        notification_delivery_cleanup_scheduler_task is None
        or notification_delivery_cleanup_scheduler_task.done()
    ):
        notification_delivery_cleanup_scheduler_task = (
            asyncio.create_task(
                notification_delivery_cleanup_scheduler.run()
            )
        )

    if (
        autonomous_workflow_scheduler_task is None
        or autonomous_workflow_scheduler_task.done()
    ):
        autonomous_workflow_scheduler_task = (
            asyncio.create_task(
                autonomous_workflow_scheduler.run()
            )
        )

    if (
        proactive_activity_scheduler_task is None
        or proactive_activity_scheduler_task.done()
    ):
        proactive_activity_scheduler_task = (
            asyncio.create_task(
                proactive_activity_scheduler.run()
            )
        )

    logging.getLogger(__name__).info(
        "NOVA reminder scheduler started automatically."
    )

    logging.getLogger(__name__).info(
        "NOVA idempotency cleanup scheduler started automatically."
    )

    logging.getLogger(__name__).info(
        "NOVA notification delivery cleanup scheduler started automatically."
    )

    logging.getLogger(__name__).info(
        "NOVA autonomous workflow scheduler started automatically."
    )

    logging.getLogger(__name__).info(
        "NOVA proactive activity scheduler started automatically."
    )


async def shutdown_event():
    global scheduler_task
    global idempotency_cleanup_scheduler_task
    global notification_delivery_cleanup_scheduler_task
    global autonomous_workflow_scheduler_task
    global proactive_activity_scheduler_task

    reminder_scheduler.stop()
    idempotency_cleanup_scheduler.stop()
    autonomous_workflow_scheduler.stop()
    proactive_activity_scheduler.stop()

    if scheduler_task is not None:
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass

        scheduler_task = None

    if idempotency_cleanup_scheduler_task is not None:
        try:
            await idempotency_cleanup_scheduler_task
        except asyncio.CancelledError:
            pass

        idempotency_cleanup_scheduler_task = None

    if notification_delivery_cleanup_scheduler_task is not None:
        try:
            await notification_delivery_cleanup_scheduler_task
        except asyncio.CancelledError:
            pass

        notification_delivery_cleanup_scheduler_task = None

    if autonomous_workflow_scheduler_task is not None:
        try:
            await autonomous_workflow_scheduler_task
        except asyncio.CancelledError:
            pass

        autonomous_workflow_scheduler_task = None

    if proactive_activity_scheduler_task is not None:
        try:
            await proactive_activity_scheduler_task
        except asyncio.CancelledError:
            pass

        proactive_activity_scheduler_task = None

    logging.getLogger(__name__).info(
        "NOVA reminder scheduler stopped."
    )

    logging.getLogger(__name__).info(
        "NOVA idempotency cleanup scheduler stopped."
    )

    logging.getLogger(__name__).info(
        "NOVA notification delivery cleanup scheduler stopped."
    )

    logging.getLogger(__name__).info(
        "NOVA autonomous workflow scheduler stopped."
    )

    logging.getLogger(__name__).info(
        "NOVA proactive activity scheduler stopped."
    )


@app.get("/")
def home():
    return {
        "message": "NOVA backend is running!"
    }


@app.get(
    "/metrics",
    include_in_schema=False,
)
def metrics() -> Response:
    """
    Expose Prometheus-compatible application metrics.

    The endpoint intentionally remains outside user authentication;
    deployment/network policy should restrict scrape access.
    """
    body, content_type = generate_metrics()

    return Response(
        content=body,
        media_type=content_type,
    )


@app.get(
    "/users/{user_id}/notification-preferences",
    response_model=NotificationPreferencesResponse,
)
def get_notification_preferences(
    user_id: str,
    current_user_id: CurrentUserId,
):
    authorize_user_scope(
        requested_user_id=user_id,
        current_user_id=current_user_id,
    )

    try:
        preferences = (
            user_notification_preferences_service
            .get_or_create(
                user_id=current_user_id
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return _notification_preferences_payload(
        preferences
    )


@app.put(
    "/users/{user_id}/notification-preferences",
    response_model=NotificationPreferencesResponse,
)
def update_notification_preferences(
    user_id: str,
    request: NotificationPreferencesUpdateRequest,
    current_user_id: CurrentUserId,
):
    authorize_user_scope(
        requested_user_id=user_id,
        current_user_id=current_user_id,
    )

    try:
        preferences = (
            user_notification_preferences_service
            .update(
                user_id=current_user_id,
                timezone_name=request.timezone,
                daily_activity_digest_enabled=(
                    request.daily_activity_digest_enabled
                ),
                delivery_hour=request.delivery_hour,
                delivery_minute=request.delivery_minute,
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return _notification_preferences_payload(
        preferences
    )


def _execute_chat(
    *,
    request: ChatRequest,
    current_user_id: str,
) -> dict:
    conversation_execution_service.bind_dependencies(
        conversation_service=conversation_service,
        execution_service=execution_service,
        llm_service=llm_service,
        memory_service=memory_service,
    )

    return conversation_execution_service.execute_message(
        user_id=current_user_id,
        message=request.message,
        conversation_id=request.conversation_id,
        execution_context=ExecutionContext.interactive(),
    )


@app.post("/chat")
def chat(
    request: ChatRequest,
    current_user_id: CurrentUserId,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
):
    normalized_message = request.message.strip()

    if not normalized_message:
        return {
            "error": "message cannot be empty"
        }

    claim = None

    if idempotency_key is not None:
        request_hash = (
            IdempotencyService.build_request_hash(
                {
                    "message": normalized_message,
                    "conversation_id": request.conversation_id,
                }
            )
        )

        claim = idempotency_service.claim_or_replay(
            user_id=current_user_id,
            endpoint="/chat",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

        if claim["status"] == "conflict":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Idempotency-Key was already used "
                    "for a different request."
                ),
            )

        if claim["status"] == "in_progress":
            raise HTTPException(
                status_code=409,
                detail=(
                    "This request is already being processed."
                ),
                headers={
                    "Retry-After": "1",
                },
            )

        if claim["status"] == "replay":
            return claim["response_body"]

    try:
        response_payload = _execute_chat(
            request=ChatRequest(
                message=normalized_message,
                conversation_id=request.conversation_id,
            ),
            current_user_id=current_user_id,
        )
    except Exception:
        if claim is not None and claim.get("claim_token"):
            try:
                idempotency_service.fail(
                    record_id=claim["record_id"],
                    claim_token=claim["claim_token"],
                    error="Chat request processing failed.",
                )
            except Exception:
                pass

        raise

    if claim is not None and claim.get("claim_token"):
        try:
            idempotency_service.complete(
                record_id=claim["record_id"],
                claim_token=claim["claim_token"],
                response_status=200,
                response_body=jsonable_encoder(
                    response_payload
                ),
            )
        except Exception:
            pass

    return response_payload