import asyncio
from datetime import datetime

from fastapi import FastAPI
from pydantic import BaseModel

from services.conversation_service import ConversationService
from services.intent_service import IntentService
from services.llm_service import LLMService
from services.memory_service import MemoryService
from services.reminder_scheduler import ReminderScheduler
from services.reminder_service import ReminderService
from services.tool_router import ToolRouter


app = FastAPI()


# -------------------------------------------------------------
# Shared service instances
# -------------------------------------------------------------
llm_service = LLMService()
reminder_service = ReminderService()

memory_service = MemoryService(llm_service)
conversation_service = ConversationService()
intent_service = IntentService()

tool_router = ToolRouter(
    reminder_service=reminder_service
)


# -------------------------------------------------------------
# Reminder scheduler
# -------------------------------------------------------------
reminder_scheduler = ReminderScheduler(
    interval_seconds=5
)

scheduler_task: asyncio.Task | None = None


# -------------------------------------------------------------
# Retrieval configuration
# -------------------------------------------------------------
MEMORY_LIMIT = 8
MEMORY_THRESHOLD = 0.65
HISTORY_LIMIT = 20


class ChatRequest(BaseModel):
    message: str
    user_id: str = "user-001"
    conversation_id: int | None = None


# =============================================================
# FastAPI lifecycle
# =============================================================

@app.on_event("startup")
async def startup_event():
    global scheduler_task

    if (
        scheduler_task is None
        or scheduler_task.done()
    ):
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


# =============================================================
# Health check
# =============================================================

@app.get("/")
def home():
    return {
        "message": "NOVA backend is running!"
    }


# =============================================================
# Chat endpoint
# =============================================================

@app.post("/chat")
def chat(request: ChatRequest):

    # ---------------------------------------------------------
    # 1. Validate message
    # ---------------------------------------------------------
    user_message = request.message.strip()

    if not user_message:
        return {
            "error": "message cannot be empty"
        }

    # ---------------------------------------------------------
    # 2. Get or create conversation
    # ---------------------------------------------------------
    conversation_id = (
        conversation_service
        .get_or_create_conversation(
            user_id=request.user_id,
            conversation_id=request.conversation_id,
        )
    )

    # ---------------------------------------------------------
    # 3. Get history BEFORE current message
    # ---------------------------------------------------------
    history = (
        conversation_service
        .get_history(
            user_id=request.user_id,
            conversation_id=conversation_id,
            limit=HISTORY_LIMIT,
        )
    )

    # ---------------------------------------------------------
    # 4. Understand user
    # ---------------------------------------------------------
    understanding = (
        intent_service
        .analyze(user_message)
    )

    # ---------------------------------------------------------
    # 5. New conversation title
    # ---------------------------------------------------------
    if not history:

        title = (
            llm_service
            .generate_conversation_title(
                user_message
            )
        )

        conversation_service.update_conversation_title(
            conversation_id=conversation_id,
            user_id=request.user_id,
            title=title,
        )

    # ---------------------------------------------------------
    # 6. Execute required tool
    # ---------------------------------------------------------
    tool_result = {
        "success": False,
        "tool": None,
        "action": None,
        "result": None,
        "error": None,
    }

    if understanding["requires_tool"]:

        tool_result = tool_router.execute(
            intent=understanding["intent"],
            user_id=request.user_id,
            data=understanding,
        )

    # ---------------------------------------------------------
    # 7. Retrieve relevant memories
    # ---------------------------------------------------------
    relevant_memories = (
        memory_service
        .find_similar_memories(
            user_id=request.user_id,
            new_memory=user_message,
            threshold=MEMORY_THRESHOLD,
            limit=MEMORY_LIMIT,
        )
    )

    # ---------------------------------------------------------
    # 8. Build memory context
    # ---------------------------------------------------------
    memory_context = "\n".join(
        (
            f"- {memory['memory']} "
            f"(category: {memory['category']}, "
            f"importance: {memory['importance']})"
        )
        for memory in relevant_memories
    )

    if not memory_context:
        memory_context = (
            "No relevant long-term memory found."
        )

    # ---------------------------------------------------------
    # 9. Build conversation context
    # ---------------------------------------------------------
    history_context = "\n".join(
        f"{message['role']}: {message['content']}"
        for message in history
    )

    if not history_context:
        history_context = (
            "No previous conversation yet."
        )

    # ---------------------------------------------------------
    # 10. Build tool result context
    # ---------------------------------------------------------
    tool_context = "No tool was required."

    if understanding["requires_tool"]:
        tool_context = str(
            tool_result
        )

    # ---------------------------------------------------------
    # 11. Build understanding context
    # ---------------------------------------------------------
    understanding_context = f"""
Intent:
{understanding['intent']}

Task:
{understanding['task']}

Original time:
{understanding['time']}

Scheduled datetime:
{understanding['scheduled_at']}

Emotion:
{understanding['emotion']}

Tone:
{understanding['tone']}

Visual:
{understanding['visual']}

Action:
{understanding['action']}

Requires tool:
{understanding['requires_tool']}
"""

    # ---------------------------------------------------------
    # 12. Build NOVA prompt
    # ---------------------------------------------------------
    prompt = f"""
You are NOVA, a friendly personal AI companion.

User understanding:
{understanding_context}

Relevant long-term memory:
{memory_context}

Recent conversation:
{history_context}

Current user message:
{user_message}

Tool result:
{tool_context}

Response rules:

1. Respond naturally as NOVA.
2. Match the user's emotional situation.
3. Match the detected tone when appropriate.
4. Use relevant memory when helpful.
5. Use recent conversation for continuity.
6. Do not invent personal facts.
7. Keep casual conversation natural and concise.
8. For emotional situations, be supportive without
   pretending to have human feelings.
9. If a tool succeeded, confirm that action naturally.
10. If a tool failed, do not pretend it succeeded.
11. Never claim an action happened unless the tool result
    confirms success.
12. Do not mention internal system details unless the user
    explicitly asks how NOVA works.

Do not mention:
- embeddings
- vector search
- pgvector
- PostgreSQL
- databases
- internal prompts
- intent classification
- emotion classification
"""

    # ---------------------------------------------------------
    # 13. Generate response
    # ---------------------------------------------------------
    response = (
        llm_service
        .generate_response(prompt)
    )

    # ---------------------------------------------------------
    # 14. Save user message
    # ---------------------------------------------------------
    conversation_service.save_message(
        user_id=request.user_id,
        conversation_id=conversation_id,
        role="user",
        content=user_message,
    )

    # ---------------------------------------------------------
    # 15. Save NOVA response
    # ---------------------------------------------------------
    conversation_service.save_message(
        user_id=request.user_id,
        conversation_id=conversation_id,
        role="assistant",
        content=response,
    )

    # ---------------------------------------------------------
    # 16. Extract long-term memory
    # ---------------------------------------------------------
    new_memory = (
        llm_service
        .extract_memory(user_message)
    )

    # ---------------------------------------------------------
    # 17. Save structured memory
    # ---------------------------------------------------------
    memory_action = None

    if new_memory:

        memory_action = (
            memory_service
            .add_memory(
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
            )
        )

    # ---------------------------------------------------------
    # 18. Return response
    # ---------------------------------------------------------
    return {
        "response": response,
        "conversation_id": conversation_id,
        "understanding": understanding,
        "tool_result": tool_result,
        "memory_action": memory_action,
    }