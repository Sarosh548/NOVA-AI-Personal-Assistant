import asyncio

from fastapi import FastAPI
from pydantic import BaseModel

from agent.graph import build_graph
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


app = FastAPI()

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
notification_service = NotificationService()

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
    user_id: str = "user-001"
    conversation_id: int | None = None


@app.on_event("startup")
async def startup_event():
    global scheduler_task
    global autonomous_workflow_scheduler_task
    global proactive_activity_scheduler_task

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


@app.post("/chat")
def chat(
    request: ChatRequest,
):
    user_message = request.message.strip()

    if not user_message:
        return {
            "error": "message cannot be empty"
        }

    conversation_id = (
        conversation_service.get_or_create_conversation(
            user_id=request.user_id,
            conversation_id=request.conversation_id,
        )
    )

    history = (
        conversation_service.get_context_history(
            user_id=request.user_id,
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
            user_id=request.user_id,
            title=title,
        )

    execution_context = (
        ExecutionContext.interactive()
    )

    result = execution_service.execute(
        user_id=request.user_id,
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
        user_id=request.user_id,
        conversation_id=conversation_id,
        role="user",
        content=user_message,
    )

    conversation_service.save_message(
        user_id=request.user_id,
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
                user_id=request.user_id,
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