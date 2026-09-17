from langgraph.graph import END, START, StateGraph

from agent.state import NOVAState
from services.confirmation_service import (
    ConfirmationService,
)
from services.execution_context import (
    DEFAULT_AUTONOMOUS_CONTEXT,
    DEFAULT_INTERACTIVE_CONTEXT,
    ExecutionContext,
)
from services.intent_service import IntentService
from services.llm_service import LLMService
from services.memory_service import MemoryService
from services.permission_service import PermissionService
from services.planner_service import PlannerService
from services.tool_router import ToolRouter


llm_service = LLMService()
memory_service = MemoryService(llm_service)
intent_service = IntentService()
planner_service = PlannerService()
permission_service = PermissionService()
confirmation_service = ConfirmationService()

tool_router = ToolRouter()


DEFAULT_TOOL_RESULT = {
    "success": False,
    "tool": None,
    "action": None,
    "result": None,
    "error": None,
}


DEFAULT_CONFIRMATION = {
    "id": None,
    "status": None,
    "tool": None,
    "action": None,
    "reason": None,
}


def _get_execution_context(
    state: NOVAState,
) -> ExecutionContext:
    """
    Resolve the execution context for the current graph run.

    New executions should provide execution_context directly.

    The user_requested fallback exists temporarily for backward
    compatibility with older callers/tests that still provide only
    the legacy boolean field.

    Missing context defaults to autonomous mode so that a missing
    execution context does not accidentally grant interactive
    state-changing permissions.
    """

    execution_context = state.get(
        "execution_context"
    )

    if isinstance(
        execution_context,
        ExecutionContext,
    ):
        return execution_context

    if state.get("user_requested") is True:
        return DEFAULT_INTERACTIVE_CONTEXT

    return DEFAULT_AUTONOMOUS_CONTEXT


def confirmation_node(
    state: NOVAState,
) -> NOVAState:
    """
    Check whether the current message is resolving an existing
    pending confirmation.

    Approval:
        pending confirmation
        -> approve confirmation
        -> rebuild exact saved plan
        -> allow tool execution

    Rejection:
        pending confirmation
        -> reject confirmation
        -> no tool execution

    Ambiguous/no pending confirmation:
        continue normal NOVA flow.
    """

    user_id = state.get(
        "user_id",
        "user-001",
    )

    conversation_id = state.get(
        "conversation_id"
    )

    message = state.get(
        "user_message",
        "",
    )

    response_type = (
        confirmation_service.parse_response(
            message
        )
    )

    pending = (
        confirmation_service
        .get_latest_pending_confirmation(
            user_id=user_id,
            conversation_id=conversation_id,
        )
    )

    if pending is None:
        return {
            **state,
            "confirmation": dict(
                DEFAULT_CONFIRMATION
            ),
        }

    if response_type is None:
        return {
            **state,
            "confirmation": {
                "id": pending["id"],
                "status": pending["status"],
                "tool": pending["tool"],
                "action": pending["action"],
                "reason": pending["reason"],
            },
        }

    if response_type == "approve":
        approved = (
            confirmation_service.approve_confirmation(
                user_id=user_id,
                confirmation_id=pending["id"],
            )
        )

        if approved is None:
            return {
                **state,
                "confirmation": dict(
                    DEFAULT_CONFIRMATION
                ),
            }

        if approved["status"] != "approved":
            return {
                **state,
                "confirmation": {
                    "id": approved["id"],
                    "status": approved["status"],
                    "tool": approved["tool"],
                    "action": approved["action"],
                    "reason": approved["reason"],
                },
                "plan": {},
                "permission": {
                    "allowed": False,
                    "requires_confirmation": False,
                    "reason": (
                        "The confirmation could not "
                        "be approved."
                    ),
                },
            }

        confirmed_plan = {
            "requires_tool": True,
            "tool": approved["tool"],
            "action": approved["action"],
            "data": approved["data"],
            "reason": (
                "Action approved by the user "
                "through a pending confirmation."
            ),
        }

        permission = {
            "allowed": True,
            "requires_confirmation": False,
            "reason": (
                "The user explicitly approved the "
                "pending confirmation."
            ),
        }

        confirmation = {
            "id": approved["id"],
            "status": approved["status"],
            "tool": approved["tool"],
            "action": approved["action"],
            "reason": approved["reason"],
        }

        return {
            **state,
            "plan": confirmed_plan,
            "permission": permission,
            "confirmation": confirmation,
        }

    rejected = (
        confirmation_service.reject_confirmation(
            user_id=user_id,
            confirmation_id=pending["id"],
        )
    )

    if rejected is None:
        return {
            **state,
            "confirmation": dict(
                DEFAULT_CONFIRMATION
            ),
        }

    return {
        **state,
        "plan": {},
        "permission": {
            "allowed": False,
            "requires_confirmation": False,
            "reason": (
                "The user rejected the pending action."
            ),
        },
        "confirmation": {
            "id": rejected["id"],
            "status": rejected["status"],
            "tool": rejected["tool"],
            "action": rejected["action"],
            "reason": rejected["reason"],
        },
    }


def route_after_confirmation(
    state: NOVAState,
) -> str:
    """
    Route after checking for a pending confirmation.

    approved:
        claim and execute through the tool node.

    rejected:
        go to the agent without execution.

    anything else:
        continue normal NOVA processing.
    """

    confirmation = state.get(
        "confirmation",
        {},
    )

    status = confirmation.get(
        "status"
    )

    if status == "approved":
        return "tool"

    if status == "rejected":
        return "agent"

    return "memory"


def memory_node(state: NOVAState) -> NOVAState:
    """
    Retrieve relevant long-term memory for the current user.
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


def planner_node(state: NOVAState) -> NOVAState:
    """
    Convert NOVA's understanding into a structured plan.

    The planner does not execute tools.
    """

    available_tools = (
        tool_router.get_available_tools()
    )

    plan = planner_service.create_plan(
        understanding=state["understanding"],
        available_tools=available_tools,
    )

    return {
        **state,
        "plan": {
            "requires_tool": plan.requires_tool,
            "tool": plan.tool,
            "action": plan.action,
            "data": plan.data,
            "reason": plan.reason,
        },
    }


def route_after_understanding(
    state: NOVAState,
) -> str:
    """
    Backward-compatible routing helper.

    The actual graph routes through confirmation and
    permission nodes.
    """

    plan = state.get("plan")

    if plan is None:
        understanding = state["understanding"]

        plan_decision = planner_service.create_plan(
            understanding=understanding,
            available_tools=(
                tool_router.get_available_tools()
            ),
        )

        return (
            "tool"
            if plan_decision.requires_tool
            else "agent"
        )

    return (
        "tool"
        if plan.get("requires_tool", False)
        else "agent"
    )


def permission_node(state: NOVAState) -> NOVAState:
    """
    Perform the permission/safety check after planning
    and before tool execution.

    When confirmation is required, create a persistent
    confirmation request containing the exact planned
    tool/action/data.

    This node never executes tools.
    """

    default_permission = {
        "allowed": False,
        "requires_confirmation": False,
        "reason": "No permission check was required.",
    }

    plan = state.get(
        "plan",
        {},
    )

    if not plan.get("requires_tool"):
        return {
            **state,
            "permission": default_permission,
            "confirmation": dict(
                DEFAULT_CONFIRMATION
            ),
        }

    tool_name = plan.get("tool")
    action = plan.get("action")

    if not tool_name:
        permission = {
            "allowed": False,
            "requires_confirmation": False,
            "reason": "Planner did not select a tool.",
        }

        return {
            **state,
            "permission": permission,
            "confirmation": dict(
                DEFAULT_CONFIRMATION
            ),
        }

    if not action:
        permission = {
            "allowed": False,
            "requires_confirmation": False,
            "reason": "Planner did not select an action.",
        }

        return {
            **state,
            "permission": permission,
            "confirmation": dict(
                DEFAULT_CONFIRMATION
            ),
        }

    execution_context = _get_execution_context(
        state
    )

    decision = permission_service.check(
        user_id=state.get(
            "user_id",
            "user-001",
        ),
        tool=str(tool_name),
        action=str(action),
        user_requested=(
            execution_context.user_requested
        ),
    )

    permission = {
        "allowed": decision.allowed,
        "requires_confirmation": (
            decision.requires_confirmation
        ),
        "reason": decision.reason,
    }

    confirmation = dict(
        DEFAULT_CONFIRMATION
    )

    if decision.requires_confirmation:
        confirmation_data = plan.get(
            "data"
        ) or {}

        confirmation_id = (
            confirmation_service.create_confirmation(
                user_id=state.get(
                    "user_id",
                    "user-001",
                ),
                conversation_id=state.get(
                    "conversation_id"
                ),
                tool=str(tool_name),
                action=str(action),
                data=confirmation_data,
                reason=decision.reason,
            )
        )

        confirmation = {
            "id": confirmation_id,
            "status": "pending",
            "tool": str(tool_name),
            "action": str(action),
            "reason": decision.reason,
        }

    return {
        **state,
        "permission": permission,
        "confirmation": confirmation,
    }


def route_after_permission(
    state: NOVAState,
) -> str:
    """
    Only an explicitly allowed permission decision can
    reach the tool node.

    Confirmation-required and denied actions go to the
    agent without executing anything.
    """

    plan = state.get(
        "plan",
        {},
    )

    permission = state.get(
        "permission",
        {},
    )

    if not plan.get("requires_tool"):
        return "agent"

    if permission.get("allowed") is True:
        return "tool"

    return "agent"


def tool_node(state: NOVAState) -> NOVAState:
    """
    Execute a permitted tool.

    Confirmed actions use an atomic database claim before
    execution. The exact tool/action/data are loaded from
    the claimed confirmation record rather than trusting
    the current graph state.

    This makes an approved confirmation one-time executable.
    """

    tool_result = dict(
        DEFAULT_TOOL_RESULT
    )

    plan = state.get(
        "plan",
        {},
    )

    permission = state.get(
        "permission",
        {},
    )

    confirmation = state.get(
        "confirmation",
        {},
    )

    if not plan.get("requires_tool"):
        return {
            **state,
            "tool_result": tool_result,
        }

    if permission.get("allowed") is not True:
        tool_name = plan.get("tool")
        action = plan.get("action")

        tool_result = {
            "success": False,
            "tool": (
                str(tool_name)
                if tool_name
                else None
            ),
            "action": (
                str(action)
                if action
                else None
            ),
            "result": None,
            "error": (
                permission.get("reason")
                or "Tool execution is not permitted."
            ),
        }

        return {
            **state,
            "tool_result": tool_result,
        }

    # -------------------------------------------------
    # Confirmed action:
    # atomically claim the approved confirmation first.
    # -------------------------------------------------

    confirmation_id = confirmation.get(
        "id"
    )

    is_confirmed_execution = (
        confirmation.get("status")
        == "approved"
        and confirmation_id is not None
    )

    if is_confirmed_execution:
        claimed = (
            confirmation_service.claim_confirmation(
                user_id=state.get(
                    "user_id",
                    "user-001",
                ),
                confirmation_id=confirmation_id,
            )
        )

        if claimed is None:
            tool_result = {
                "success": False,
                "tool": confirmation.get(
                    "tool"
                ),
                "action": confirmation.get(
                    "action"
                ),
                "result": None,
                "error": (
                    "This confirmation is no longer "
                    "available for execution."
                ),
            }

            return {
                **state,
                "tool_result": tool_result,
            }

        # ---------------------------------------------
        # SECURITY:
        # Use the exact action saved in the database.
        # Do not trust a modified in-memory plan.
        # ---------------------------------------------

        tool_name = claimed["tool"]
        action = claimed["action"]
        plan_data = claimed["data"]

    else:
        tool_name = plan.get("tool")

        if not tool_name:
            tool_result = {
                "success": False,
                "tool": None,
                "action": plan.get("action"),
                "result": None,
                "error": (
                    "Planner did not select a tool."
                ),
            }

            return {
                **state,
                "tool_result": tool_result,
            }

        action = plan.get("action")
        plan_data = plan.get("data") or {}

    try:
        tool_result = tool_router.execute(
            intent=str(tool_name),
            user_id=state.get(
                "user_id",
                "user-001",
            ),
            data=plan_data,
        )

    except Exception:
        tool_result = {
            "success": False,
            "tool": str(tool_name),
            "action": str(action),
            "result": None,
            "error": (
                "Tool execution failed."
            ),
        }

    # -------------------------------------------------
    # Confirmed action:
    # finalize the one-time confirmation after execution.
    # -------------------------------------------------

    if is_confirmed_execution:
        finished = (
            confirmation_service.finish_confirmation(
                user_id=state.get(
                    "user_id",
                    "user-001",
                ),
                confirmation_id=confirmation_id,
                success=(
                    tool_result.get("success")
                    is True
                ),
            )
        )

        if finished is not None:
            confirmation = {
                "id": finished["id"],
                "status": finished["status"],
                "tool": finished["tool"],
                "action": finished["action"],
                "reason": finished["reason"],
            }

    return {
        **state,
        "confirmation": confirmation,
        "tool_result": tool_result,
    }


def agent_node(state: NOVAState) -> NOVAState:
    """
    Generate NOVA's final response.
    """

    understanding = state.get(
        "understanding",
        {},
    )

    plan = state.get(
        "plan",
        {},
    )

    permission = state.get(
        "permission",
        {
            "allowed": False,
            "requires_confirmation": False,
            "reason": "No permission check was performed.",
        },
    )

    confirmation = state.get(
        "confirmation",
        dict(DEFAULT_CONFIRMATION),
    )

    tool_result = state.get(
        "tool_result",
        dict(DEFAULT_TOOL_RESULT),
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

Reminder action:
{understanding.get('reminder_action')}

Reminder reference:
{understanding.get('reminder_reference')}

Reminder ID:
{understanding.get('reminder_id')}

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

    plan_context = f"""
Planner requires tool:
{plan.get('requires_tool')}

Planner tool:
{plan.get('tool')}

Planner action:
{plan.get('action')}

Planner reason:
{plan.get('reason')}
"""

    permission_context = f"""
Permission allowed:
{permission.get('allowed')}

Permission requires confirmation:
{permission.get('requires_confirmation')}

Permission reason:
{permission.get('reason')}
"""

    confirmation_context = f"""
Confirmation ID:
{confirmation.get('id')}

Confirmation status:
{confirmation.get('status')}

Confirmation tool:
{confirmation.get('tool')}

Confirmation action:
{confirmation.get('action')}

Confirmation reason:
{confirmation.get('reason')}
"""

    tool_context = "No tool was required."

    if (
        plan.get("requires_tool")
        and tool_result.get("tool")
    ):
        tool_context = str(tool_result)

    prompt = f"""
You are NOVA, a friendly personal AI companion.

User understanding:
{understanding_context}

Planner decision:
{plan_context}

Permission decision:
{permission_context}

Confirmation state:
{confirmation_context}

Relevant long-term memory:
{state.get("memory_context", "")}

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
6. Understand follow-up references using conversation history.
7. Do not invent personal facts.
8. Keep casual conversation natural and concise.
9. For emotional situations, be supportive without pretending
   to have human feelings.
10. If a tool succeeded, confirm that action naturally.
11. If a tool failed, do not pretend it succeeded.
12. Never claim an action happened unless the tool result
    confirms success.
13. If permission was denied, do not pretend the action
    was performed.
14. If confirmation is required, clearly ask the user for
    approval and do not claim the action has happened.
15. If a confirmation was rejected, clearly state that the
    action was not performed.
16. If a confirmation was approved, describe the actual
    tool result rather than claiming success automatically.
17. If a confirmed action has status "consumed", it has already
    been executed and must not be executed again.
18. Do not mention internal system details unless explicitly asked.
19. Do not mention embeddings, vector search, pgvector,
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
        "confirmation",
        confirmation_node,
    )

    graph.add_node(
        "memory",
        memory_node,
    )

    graph.add_node(
        "understanding",
        understanding_node,
    )

    graph.add_node(
        "planner",
        planner_node,
    )

    graph.add_node(
        "permission",
        permission_node,
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
        "confirmation",
    )

    graph.add_conditional_edges(
        "confirmation",
        route_after_confirmation,
        {
            "tool": "tool",
            "agent": "agent",
            "memory": "memory",
        },
    )

    graph.add_edge(
        "memory",
        "understanding",
    )

    graph.add_edge(
        "understanding",
        "planner",
    )

    graph.add_edge(
        "planner",
        "permission",
    )

    graph.add_conditional_edges(
        "permission",
        route_after_permission,
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