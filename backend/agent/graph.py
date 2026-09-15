from langgraph.graph import END, START, StateGraph

from agent.state import NOVAState
from services.llm_service import LLMService
from services.memory_service import MemoryService


llm_service = LLMService()
memory_service = MemoryService(llm_service)


def memory_node(state: NOVAState) -> NOVAState:
    """
    Retrieve relevant memory for the current user message.

    Strategy:
    1. Try semantic retrieval first.
    2. If nothing relevant is found, fall back to stable
       profile memories.
    """

    user_message = state["user_message"]

    semantic_memories = (
        memory_service.find_similar_memories(
            user_id="user-001",
            new_memory=user_message,
            threshold=0.65,
            limit=8,
        )
    )

    if semantic_memories:
        memory_context = "\n".join(
            f"- {memory['memory']} "
            f"(category: {memory['category']}, "
            f"importance: {memory['importance']})"
            for memory in semantic_memories
        )

    else:
        profile_memories = (
            memory_service.get_profile_memories(
                user_id="user-001",
                limit=20,
            )
        )

        memory_context = "\n".join(
            f"- {memory['memory']} "
            f"(category: {memory['category']}, "
            f"importance: {memory['importance']})"
            for memory in profile_memories
        )

        if not memory_context:
            memory_context = (
                "No relevant long-term memory found."
            )

    return {
        **state,
        "memory_context": memory_context,
    }


def agent_node(state: NOVAState) -> NOVAState:
    """
    Generate NOVA's response using retrieved memory context.
    """

    prompt = f"""
You are NOVA, a friendly personal AI companion.

Relevant long-term memory:
{state["memory_context"]}

Current user message:
{state["user_message"]}

Rules:
- Respond naturally.
- Use relevant memory when helpful.
- When the user asks what you know about them,
  use the supplied profile information.
- Do not invent personal facts.
- Do not mention internal memory systems.
- Keep the response concise and natural.
"""

    response = llm_service.generate_response(
        prompt
    )

    return {
        **state,
        "response": response,
    }


def build_graph():
    graph = StateGraph(NOVAState)

    graph.add_node(
        "memory",
        memory_node,
    )

    graph.add_node(
        "agent",
        agent_node,
    )

    graph.add_edge(
        START,
        "memory",
    )

    graph.add_edge(
        "memory",
        "agent",
    )

    graph.add_edge(
        "agent",
        END,
    )

    return graph.compile()