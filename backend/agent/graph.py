from typing import Any

from langgraph.graph import END, START, StateGraph

from agent.state import NOVAState
from services.intent_service import IntentService
from services.llm_service import LLMService
from services.memory_service import MemoryService
from services.tool_router import ToolRouter


llm_service = LLMService()
memory_service = MemoryService(llm_service)
intent_service = IntentService()

tool_router = ToolRouter()


def memory_node(state: NOVAState) -> NOVAState:
    """
    Retrieve relevant memory for the current user.

    Semantic retrieval is attempted first.
    Profile memories are used as a fallback for
    broad personal/profile questions.
    """

    user_id = state.get("user_id", "user-001")
    user_message = state["user_message"]

    semantic_memories = memory_service.find_similar_memories(
        user_id=user_id,
        new_memory=user_message,
        threshold=0.65,
        limit=8,
    )

    if semantic_memories:
        memories = semantic_memories

    else:
        memories = memory_service.get_profile_memories(
            user_id=user_id,
            limit=20,
        )

    memory_context = "\n".join(
        f"- {memory['memory']} "
        f"(category: {memory['category']}, "
        f"importance: {memory['importance']})"
        for memory in memories
    )

    if not memory_context:
        memory_context = "No relevant long-term memory found."

    return {
        **state,
        "memory_context": memory_context,
    }


def understanding_node(state: NOVAState) -> NOVAState:
    """
    Understand the user's message before deciding
    whether a tool is required.
    """

    understanding = intent_service.analyze(
        state["user_message"]
    )

    return {
        **state,
        "understanding": understanding,
    }


def tool_node(state: NOVAState) -> NOVAState:
    """
    Execute a tool only when the intent layer says
    that a tool is required.
    """

    understanding = state["understanding"]

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
            user_id=state["user_id"],
            data=understanding,
        )

    return {
        **state,
        "tool_result": tool_result,
    }


def agent_node(state: NOVAState) -> NOVAState:
    """
    Generate NOVA's final response using:

    - current message
    - recent conversation
    - long-term memory
    - user understanding
    - tool result
    """

    understanding = state["understanding"]
    tool_result = state["tool_result"]

    history_context = "\n".join(
        f"{message['role']}: {message['content']}"
        for message in state["history"]
    )

    if not history_context:
        history_context = "No previous conversation yet."

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

    tool_context = "No tool was required."

    if understanding["requires_tool"]:
        tool_context = str(tool_result)

    prompt = f"""
You are NOVA, a friendly personal AI companion.

User understanding:
{understanding_context}

Relevant long-term memory:
{state["memory_context"]}

Recent conversation:
{history_context}

Current user message:
{state["user_message"]}

Tool result:
{tool_context}

Response rules:
1. Respond naturally as NOVA.
2. Match the user's emotional situation.
3. Match detected tone when appropriate.
4. Use relevant memory when helpful.
5. Use recent conversation for continuity.
6. Do not invent personal facts.
7. Keep casual conversation natural and concise.
8. For emotional situations, be supportive without pretending to have human feelings.
9. If a tool succeeded, confirm that action naturally.
10. If a tool failed, do not pretend it succeeded.
11. Never claim an action happened unless tool result confirms success.
12. Do not mention internal system details unless explicitly asked.
13. Do not mention embeddings, vector search, pgvector,
    PostgreSQL, databases, internal prompts, or intent classification.
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
        "understanding",
        understanding_node,
    )

    graph.add_node(
        "tool",
        tool_node,
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
        "understanding",
    )

    graph.add_edge(
        "understanding",
        "tool",
    )

    graph.add_edge(
        "tool",
        "agent",
    )

    graph.add_edge(
        "agent",
        END,
    )

    return graph.compile()