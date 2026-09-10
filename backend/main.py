from fastapi import FastAPI
from pydantic import BaseModel

from services.llm_service import LLMService
from services.memory_service import MemoryService


app = FastAPI()

llm_service = LLMService()
memory_service = MemoryService()


class ChatRequest(BaseModel):
    message: str
    user_id: str = "user-001"


@app.get("/")
def home():
    return {"message": "NOVA backend is running!"}


@app.post("/chat")
def chat(request: ChatRequest):
    new_memory = llm_service.extract_memory(request.message)

    if new_memory:
        memory_service.add_memory(
            user_id=request.user_id,
            memory_text=new_memory,
            category="personal",
            importance="medium",
        )

    memories = memory_service.get_memories(request.user_id)

    memory_context = "\n".join(
        f"- {memory}" for memory in memories
    )

    prompt = f"""
Relevant memory about the user:
{memory_context if memory_context else "No relevant long-term memory yet."}

Current user message:
{request.message}

Respond naturally as NOVA.
Use relevant memory when helpful.
Do not mention the memory system unless the user asks about it.
"""

    response = llm_service.generate_response(prompt)

    return {
        "response": response,
        "memories": memories,
    }