from fastapi import FastAPI
from pydantic import BaseModel

from services.conversation_service import ConversationService
from services.llm_service import LLMService
from services.memory_service import MemoryService


app = FastAPI()


# Shared service instances
llm_service = LLMService()
memory_service = MemoryService(llm_service)
conversation_service = ConversationService()

# Retrieval configuration
MEMORY_LIMIT = 8
MEMORY_THRESHOLD = 0.65
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
    # 2. Get recent conversation history
    # ---------------------------------------------------------
    history = conversation_service.get_history(
        user_id=request.user_id,
        conversation_id=conversation_id,
        limit=HISTORY_LIMIT,
    )

    # ---------------------------------------------------------
    # 3. Retrieve relevant long-term memories
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
    # 4. Convert recent history into prompt context
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

Use relevant memory and recent conversation when helpful.

Do not mention:
- internal memory
- embeddings
- vector search
- PostgreSQL
- databases
- conversation storage

unless the user explicitly asks how NOVA works.

Do not invent personal facts that are not present
in the provided context.
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
    # 9. Extract useful long-term memory
    # ---------------------------------------------------------
    new_memory = llm_service.extract_memory(
        request.message
    )

    # ---------------------------------------------------------
    # 10. Save structured memory
    #
    # LLMService now returns:
    # {
    #     "memory_text": "...",
    #     "category": "...",
    #     "importance": "..."
    # }
    #
    # MemoryService handles semantic deduplication.
    # ---------------------------------------------------------
    if new_memory:
        memory_service.add_memory(
            user_id=request.user_id,
            memory_text=new_memory["memory_text"],
            category=new_memory["category"],
            importance=new_memory["importance"],
        )

    # ---------------------------------------------------------
    # 11. Return only the public API response
    # ---------------------------------------------------------
    return {
        "response": response,
        "conversation_id": conversation_id,
    }