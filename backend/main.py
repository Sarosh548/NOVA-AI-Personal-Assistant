from fastapi import FastAPI
from pydantic import BaseModel

from services.llm_service import LLMService
from services.memory_service import MemoryService
from services.conversation_service import ConversationService


app = FastAPI()

llm_service = LLMService()
memory_service = MemoryService()
conversation_service = ConversationService()


class ChatRequest(BaseModel):
    message: str
    user_id: str = "user-001"
    conversation_id: int | None = None


@app.get("/")
def home():
    return {"message": "NOVA backend is running!"}


@app.post("/chat")
def chat(request: ChatRequest):

    # 1. Get an existing conversation or create a new one
    conversation_id = conversation_service.get_or_create_conversation(
        user_id=request.user_id,
        conversation_id=request.conversation_id,
    )

    # 2. Get previous messages for this conversation
    history = conversation_service.get_history(
        user_id=request.user_id,
        conversation_id=conversation_id,
        limit=20,
    )

    # 3. Get long-term memories
    memories = memory_service.get_memories(request.user_id)

    memory_context = "\n".join(
        f"- {memory}"
        for memory in memories
    )

    history_context = "\n".join(
        f"{message['role']}: {message['content']}"
        for message in history
    )

    # 4. Build context for NOVA
    prompt = f"""
Relevant long-term memory:
{memory_context if memory_context else "No relevant long-term memory yet."}

Previous conversation:
{history_context if history_context else "No previous conversation yet."}

Current user message:
{request.message}

Respond naturally as NOVA.
Use relevant memory and previous conversation when helpful.
Do not mention the internal memory, database, or conversation system unless the user asks.
"""

    # 5. Generate NOVA's response
    response = llm_service.generate_response(prompt)

    # 6. Save user message
    conversation_service.save_message(
        user_id=request.user_id,
        conversation_id=conversation_id,
        role="user",
        content=request.message,
    )

    # 7. Save assistant response
    conversation_service.save_message(
        user_id=request.user_id,
        conversation_id=conversation_id,
        role="assistant",
        content=response,
    )

    # 8. Extract and save useful long-term memory
    new_memory = llm_service.extract_memory(request.message)

    if new_memory:
        memory_service.add_memory(
            user_id=request.user_id,
            memory_text=new_memory,
            category="personal",
            importance="medium",
        )

    return {
        "response": response,
        "conversation_id": conversation_id,
        "memories": memories,
        "history": history,
    }