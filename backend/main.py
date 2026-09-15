import asyncio

from fastapi import FastAPI
from pydantic import BaseModel

from agent.graph import build_graph
from services.conversation_service import ConversationService
from services.llm_service import LLMService
from services.memory_service import MemoryService
from services.reminder_scheduler import ReminderScheduler
from services.reminder_service import ReminderService


app = FastAPI()


# =========================================================
# SERVICES
# =========================================================

llm_service = LLMService()
memory_service = MemoryService(llm_service)
conversation_service = ConversationService()

# LangGraph agent
agent_graph = build_graph()

# Reminder system
reminder_service = ReminderService()

reminder_scheduler = ReminderScheduler(
    interval_seconds=5
)

scheduler_task: asyncio.Task | None = None


# =========================================================
# CONSTANTS
# =========================================================

CONTEXT_MAX_MESSAGES = 12
CONTEXT_MAX_CHARACTERS = 12000


# =========================================================
# REQUEST MODEL
# =========================================================

class ChatRequest(BaseModel):
    message: str
    user_id: str = "user-001"
    conversation_id: int | None = None


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
async def startup_event():
    global scheduler_task

    if scheduler_task is None or scheduler_task.done():
        scheduler_task = asyncio.create_task(
            reminder_scheduler.run()
        )

    print("NOVA reminder scheduler started automatically.")


# =========================================================
# SHUTDOWN
# =========================================================

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

    print("NOVA reminder scheduler stopped.")


# =========================================================
# ROOT
# =========================================================

@app.get("/")
def home():
    return {
        "message": "NOVA backend is running!"
    }


# =========================================================
# CHAT
# =========================================================

@app.post("/chat")
def chat(request: ChatRequest):

    # -----------------------------------------------------
    # 1. VALIDATE MESSAGE
    # -----------------------------------------------------

    user_message = request.message.strip()

    if not user_message:
        return {
            "error": "message cannot be empty"
        }

    # -----------------------------------------------------
    # 2. GET OR CREATE CONVERSATION
    # -----------------------------------------------------

    conversation_id = (
        conversation_service.get_or_create_conversation(
            user_id=request.user_id,
            conversation_id=request.conversation_id,
        )
    )

    # -----------------------------------------------------
    # 3. LOAD BOUNDED CONVERSATION CONTEXT
    # -----------------------------------------------------

    history = conversation_service.get_context_history(
        user_id=request.user_id,
        conversation_id=conversation_id,
        max_messages=CONTEXT_MAX_MESSAGES,
        max_characters=CONTEXT_MAX_CHARACTERS,
    )

    # -----------------------------------------------------
    # 4. CREATE CONVERSATION TITLE
    # -----------------------------------------------------

    if not history:

        title = llm_service.generate_conversation_title(
            user_message
        )

        conversation_service.update_conversation_title(
            conversation_id=conversation_id,
            user_id=request.user_id,
            title=title,
        )

    # -----------------------------------------------------
    # 5. INITIAL AGENT STATE
    # -----------------------------------------------------

    initial_state = {
        "user_id": request.user_id,
        "conversation_id": conversation_id,
        "user_message": user_message,
        "history": history,

        "understanding": {},

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

    # -----------------------------------------------------
    # 6. RUN LANGGRAPH
    # -----------------------------------------------------

    result = agent_graph.invoke(
        initial_state
    )

    response = result["response"]
    understanding = result["understanding"]
    tool_result = result["tool_result"]

    # -----------------------------------------------------
    # 7. SAVE USER MESSAGE
    # -----------------------------------------------------

    conversation_service.save_message(
        user_id=request.user_id,
        conversation_id=conversation_id,
        role="user",
        content=user_message,
    )

    # -----------------------------------------------------
    # 8. SAVE NOVA RESPONSE
    # -----------------------------------------------------

    conversation_service.save_message(
        user_id=request.user_id,
        conversation_id=conversation_id,
        role="assistant",
        content=response,
    )

    # -----------------------------------------------------
    # 9. EXTRACT LONG-TERM MEMORY
    # -----------------------------------------------------

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
        )

    # -----------------------------------------------------
    # 10. RETURN RESPONSE
    # -----------------------------------------------------

    return {
        "response": response,
        "conversation_id": conversation_id,
        "understanding": understanding,
        "tool_result": tool_result,
        "memory_action": memory_action,
    }