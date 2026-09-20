import asyncio
from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

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
from services.autonomous_workflow_scheduler import (
    AutonomousWorkflowScheduler,
)
from services.conversation_service import (
    ConversationService,
)
from services.execution_context import (
    ExecutionContext,
)
from services.execution_service import (
    NOVAExecutionService,
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
from services.proactive_activity_notification_service import (
    ProactiveActivityNotificationService,
)
from services.proactive_activity_scheduler import (
    ProactiveActivityScheduler,
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


app = FastAPI()

app.include_router(auth_router)
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

scheduler_task: asyncio.Task | None = None

autonomous_workflow_scheduler_task: (
    asyncio.Task | None
) = None

proactive_activity_scheduler_task: (
    asyncio.Task | None
) = None

CONTEXT_MAX_MESSAGES = 12
CONTEXT_MAX_CHARACTERS = 12000


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


@app.on_event("startup")
async def startup_event():
    global scheduler_task
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

    print(
        "NOVA reminder scheduler started automatically."
    )

    print(
        "NOVA autonomous workflow scheduler started automatically."
    )

    print(
        "NOVA proactive activity scheduler started automatically."
    )


@app.on_event("shutdown")
async def shutdown_event():
    global scheduler_task
    global autonomous_workflow_scheduler_task
    global proactive_activity_scheduler_task

    reminder_scheduler.stop()
    autonomous_workflow_scheduler.stop()
    proactive_activity_scheduler.stop()

    if scheduler_task is not None:
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass

        scheduler_task = None

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

    print(
        "NOVA reminder scheduler stopped."
    )

    print(
        "NOVA autonomous workflow scheduler stopped."
    )

    print(
        "NOVA proactive activity scheduler stopped."
    )


@app.get("/")
def home():
    return {
        "message": "NOVA backend is running!"
    }


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


@app.post("/chat")
def chat(
    request: ChatRequest,
    current_user_id: CurrentUserId,
):
    user_message = request.message.strip()

    if not user_message:
        return {
            "error": "message cannot be empty"
        }

    conversation_id = (
        conversation_service.get_or_create_conversation(
            user_id=current_user_id,
            conversation_id=request.conversation_id,
        )
    )

    history = (
        conversation_service.get_context_history(
            user_id=current_user_id,
            conversation_id=conversation_id,
            max_messages=CONTEXT_MAX_MESSAGES,
            max_characters=CONTEXT_MAX_CHARACTERS,
        )
    )

    if not history:
        title = (
            llm_service.generate_conversation_title(
                user_message
            )
        )

        conversation_service.update_conversation_title(
            conversation_id=conversation_id,
            user_id=current_user_id,
            title=title,
        )

    execution_context = (
        ExecutionContext.interactive()
    )

    result = execution_service.execute(
        user_id=current_user_id,
        conversation_id=conversation_id,
        user_message=user_message,
        history=history,
        execution_context=execution_context,
    )

    response = result["response"]

    understanding = result[
        "understanding"
    ]

    plan = result.get(
        "plan",
        {},
    )

    permission = result.get(
        "permission",
        {},
    )

    confirmation = result.get(
        "confirmation",
        {},
    )

    tool_result = result[
        "tool_result"
    ]

    workflow_result = result.get(
        "workflow_result",
        {},
    )

    conversation_service.save_message(
        user_id=current_user_id,
        conversation_id=conversation_id,
        role="user",
        content=user_message,
    )

    conversation_service.save_message(
        user_id=current_user_id,
        conversation_id=conversation_id,
        role="assistant",
        content=response,
    )

    new_memory = (
        llm_service.extract_memory(
            user_message
        )
    )

    memory_action = None

    if new_memory:
        memory_action = (
            memory_service.add_memory(
                user_id=current_user_id,
                memory_text=new_memory[
                    "memory_text"
                ],
                category=new_memory[
                    "category"
                ],
                importance=new_memory[
                    "importance"
                ],
                user_message=user_message,
            )
        )

    return {
        "response": response,
        "conversation_id": conversation_id,
        "understanding": understanding,
        "plan": plan,
        "permission": permission,
        "confirmation": confirmation,
        "tool_result": tool_result,
        "workflow_result": workflow_result,
        "memory_action": memory_action,
    }