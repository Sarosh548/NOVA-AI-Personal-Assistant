import asyncio

from fastapi import FastAPI
from pydantic import BaseModel

from agent.graph import build_graph
from services.conversation_service import ConversationService
from services.execution_context import ExecutionContext
from services.llm_service import LLMService
from services.memory_service import MemoryService
from services.reminder_scheduler import ReminderScheduler
from services.reminder_service import ReminderService


app = FastAPI()

llm_service = LLMService()
memory_service = MemoryService(llm_service)
conversation_service = ConversationService()

agent_graph = build_graph()

reminder_service = ReminderService()
reminder_scheduler = ReminderScheduler(
    interval_seconds=5
)
scheduler_task: asyncio.Task | None = None

CONTEXT_MAX_MESSAGES = 12
CONTEXT_MAX_CHARACTERS = 12000


class ChatRequest(BaseModel):
    message: str
    user_id: str = "user-001"
    conversation_id: int | None = None


@app.on_event("startup")
async def startup_event():
    global scheduler_task

    if scheduler_task is None or scheduler_task.done():
        scheduler_task = asyncio.create_task(
            reminder_scheduler.run()
        )

    print(
        "NOVA reminder scheduler started automatically."
    )


@app.on_event("shutdown")
async def shutdown_event():
    global scheduler_task

    reminder_scheduler.stop()

    if scheduler_task is not None:
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass

        scheduler_task = None

    print(
        "NOVA reminder scheduler stopped."
    )


@app.get("/")
def home():
    return {
        "message": "NOVA backend is running!"
    }


@app.post("/chat")
def chat(request: ChatRequest):
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

    initial_state = {
        "user_id": request.user_id,
        "conversation_id": conversation_id,
        "user_message": user_message,
        "history": history,
        "understanding": {},
        "plan": {},
        "permission": {
            "allowed": False,
            "requires_confirmation": False,
            "reason": "Permission check not performed yet.",
        },
        "user_requested": execution_context.user_requested,
        "execution_context": execution_context,
        "confirmation": {
            "id": None,
            "status": None,
            "tool": None,
            "action": None,
            "reason": None,
        },
        "tool_result": {
            "success": False,
            "tool": None,
            "action": None,
            "result": None,
            "error": None,
        },
        "memory_context": "",
        "response": "",
    }

    result = agent_graph.invoke(
        initial_state
    )

    response = result["response"]
    understanding = result["understanding"]
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
    tool_result = result["tool_result"]

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

    new_memory = llm_service.extract_memory(
        user_message
    )

    memory_action = None

    if new_memory:
        memory_action = memory_service.add_memory(
            user_id=request.user_id,
            memory_text=new_memory["memory_text"],
            category=new_memory["category"],
            importance=new_memory["importance"],
            user_message=user_message,
        )

    return {
        "response": response,
        "conversation_id": conversation_id,
        "understanding": understanding,
        "plan": plan,
        "permission": permission,
        "confirmation": confirmation,
        "tool_result": tool_result,
        "memory_action": memory_action,
    }