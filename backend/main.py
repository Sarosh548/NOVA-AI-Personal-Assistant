from fastapi import FastAPI
from pydantic import BaseModel

from services.conversation_service import ConversationService
from services.llm_service import LLMService
from services.memory_service import MemoryService


app = FastAPI()


# Shared service instances
llm_service = LLMService()
memory_service = MemoryService()
conversation_service = ConversationService()


# Retrieval configuration
MEMORY_LIMIT = 8
MEMORY_THRESHOLD = 0.70
HISTORY_LIMIT = 20


class ChatRequest(BaseModel):
    message: str
    user_id: str = "user-001"
    conversation_id: int | None = None


@app.get("/")
def home():
    return {
        "message": "NOVA backend is running!"
    }


@app.post("/chat")
def chat(request: ChatRequest):

    # ---------------------------------------------------------
    # 1. Get an existing conversation or create a new one
    # ---------------------------------------------------------
    conversation_id = (
        conversation_service.get_or_create_conversation(
            user_id=request.user_id,
            conversation_id=request.conversation_id,
        )
    )

    # ---------------------------------------------------------
    # 2. Retrieve recent conversation history
    # ---------------------------------------------------------
    history = conversation_service.get_history(
        user_id=request.user_id,
        conversation_id=conversation_id,
        limit=HISTORY_LIMIT,
    )

    # ---------------------------------------------------------
    # 3. Retrieve only relevant long-term memories
    #
    # Instead of loading every memory, semantic search finds
    # memories related to the current user message.
    # ---------------------------------------------------------
    relevant_memories = memory_service.find_similar_memories(
        user_id=request.user_id,
        new_memory=request.message,
        threshold=MEMORY_THRESHOLD,
        limit=MEMORY_LIMIT,
    )

    memory_context = "\n".join(
        f"- {memory['memory']}"
        for memory in relevant_memories
    )

    if not memory_context:
        memory_context = "No relevant long-term memory found."

    # ---------------------------------------------------------
    # 4. Build recent conversation context
    # ---------------------------------------------------------
    history_context = "\n".join(
        f"{message['role']}: {message['content']}"
        for message in history
    )

    if not history_context:
        history_context = "No previous conversation yet."

    # ---------------------------------------------------------
    # 5. Build NOVA's contextual prompt
    # ---------------------------------------------------------
    prompt = f"""
Relevant long-term memory:
{memory_context}

Recent conversation:
{history_context}

Current user message:
{request.message}

Respond naturally as NOVA.

Use the relevant memory and recent conversation when helpful.
Do not mention the internal memory, embedding, database,
vector search, or conversation system unless the user
explicitly asks about how NOVA works.

Do not invent personal facts that are not present in the
provided context.
"""

    # ---------------------------------------------------------
    # 6. Generate NOVA's response
    # ---------------------------------------------------------
    response = llm_service.generate_response(prompt)

    # ---------------------------------------------------------
    # 7. Save the user's message
    # ---------------------------------------------------------
    conversation_service.save_message(
        user_id=request.user_id,
        conversation_id=conversation_id,
        role="user",
        content=request.message,
    )

    # ---------------------------------------------------------
    # 8. Save NOVA's response
    # ---------------------------------------------------------
    conversation_service.save_message(
        user_id=request.user_id,
        conversation_id=conversation_id,
        role="assistant",
        content=response,
    )

    # ---------------------------------------------------------
    # 9. Extract useful long-term information
    # ---------------------------------------------------------
    new_memory = llm_service.extract_memory(
        request.message
    )

    # ---------------------------------------------------------
    # 10. Save extracted memory + embedding
    # ---------------------------------------------------------
    if new_memory:
        memory_service.add_memory(
            user_id=request.user_id,
            memory_text=new_memory,
            category="personal",
            importance="medium",
        )

    # ---------------------------------------------------------
    # 11. Return response
    # ---------------------------------------------------------
    return {
        "response": response,
        "conversation_id": conversation_id,
        "memories": relevant_memories,
        "history": history,
    }