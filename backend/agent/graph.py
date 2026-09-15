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
    Retrieve relevant long-term memory for the current user.

    Semantic retrieval is attempted first.
    Profile memories are used as a fallback for broad
    personal/profile questions.
    """

    user_id = state.get(
        "user_id",
        "user-001",
    )

    user_message = state["user_message"]

    semantic_memories = (
        memory_service.find_similar_memories(
            user_id=user_id,
            new_memory=user_message,
            threshold=0.65,
            limit=8,
        )
    )

    if semantic_memories:
        memories = semantic_memories
    else:
        memories = (
            memory_service.get_profile_memories(
                user_id=user_id,
                limit=20,
            )
        )

    memory_context = "\n".join(
        f"- {memory['memory']} "
        f"(category: {memory['category']}, "
        f"importance: {memory['importance']})"
        for memory in memories
    )

    if not memory_context:
        memory_context = (
            "No relevant long-term memory found."
        )

    return {
        **state,
        "memory_context": memory_context,
    }


def understanding_node(state: NOVAState) -> NOVAState:
    """
    Analyze the current message using recent conversation
    history when follow-up context is required.
    """

    understanding = intent_service.analyze(
        message=state["user_message"],
        history=state.get("history", []),
    )

    return {
        **state,
        "understanding": understanding,
    }


def route_after_understanding(
    state: NOVAState,
) -> str:
    """
    Decide whether the graph should execute a tool.

    Registered executable capabilities:
        - reminder
        - task

    Everything else continues directly to the agent.
    """

    understanding = state["understanding"]

    intent = understanding.get("intent")

    requires_tool = understanding.get(
        "requires_tool",
        False,
    )

    if requires_tool and intent in {
        "reminder",
        "task",
    }:
        return "tool"

    return "agent"


def tool_node(state: NOVAState) -> NOVAState:
    """
    Execute the required registered tool.
    """

    understanding = state["understanding"]

    tool_result = {
        "success": False,
        "tool": None,
        "action": None,
        "result": None,
        "error": None,
    }

    intent = understanding.get("intent")

    if intent in {
        "reminder",
        "task",
    }:
        tool_result = tool_router.execute(
            intent=intent,
            user_id=state.get(
                "user_id",
                "user-001",
            ),
            data=understanding,
        )

    return {
        **state,
        "tool_result": tool_result,
    }


def agent_node(state: NOVAState) -> NOVAState:
    """
    Generate NOVA's final response using:

    - current user message
    - recent conversation
    - long-term memory
    - intent understanding
    - tool result
    """

    understanding = state["understanding"]

    tool_result = state.get(
        "tool_result",
        {
            "success": False,
            "tool": None,
            "action": None,
            "result": None,
            "error": None,
        },
    )

    history = state.get(
        "history",
        [],
    )

    history_context = "\n".join(
        f"{message['role']}: {message['content']}"
        for message in history
    )

    if not history_context:
        history_context = (
            "No previous conversation yet."
        )

    understanding_context = f"""
Intent:
{understanding.get('intent')}

Task:
{understanding.get('task')}

Task reference:
{understanding.get('task_reference')}

Task action:
{understanding.get('task_action')}

Task ID:
{understanding.get('task_id')}

Original time:
{understanding.get('time')}

Scheduled datetime:
{understanding.get('scheduled_at')}

Emotion:
{understanding.get('emotion')}

Tone:
{understanding.get('tone')}

Visual:
{understanding.get('visual')}

Action:
{understanding.get('action')}

Requires tool:
{understanding.get('requires_tool')}
"""

    tool_context = "No tool was required."

    if (
        understanding.get("requires_tool")
        and tool_result.get("tool")
    ):
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
6. Understand follow-up references using the conversation
   history when the understanding system provides them.
7. Do not invent personal facts.
8. Keep casual conversation natural and concise.
9. For emotional situations, be supportive without pretending
   to have human feelings.
10. If a tool succeeded, confirm that action naturally.
11. If a tool failed, do not pretend it succeeded.
12. Never claim an action happened unless the tool result
    confirms success.
13. Do not mention internal system details unless explicitly asked.
14. Do not mention embeddings, vector search, pgvector,
    PostgreSQL, databases, internal prompts, or
    intent classification.
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

    graph.add_conditional_edges(
        "understanding",
        route_after_understanding,
        {
            "tool": "tool",
            "agent": "agent",
        },
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