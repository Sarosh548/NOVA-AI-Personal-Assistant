from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent.state import NOVAState
from services.execution_context import ExecutionContext


class NOVAExecutionService:
    """
    Shared execution boundary for NOVA.

    Interactive requests and autonomous/background
    workflows use this service to execute the NOVA graph.

    The execution context is explicit so the caller cannot
    accidentally inherit interactive permissions.
    """

    def __init__(self, agent_graph: Any):
        self.agent_graph = agent_graph

    @staticmethod
    def build_initial_state(
        *,
        user_id: str,
        conversation_id: int | None,
        user_message: str,
        history: list[dict[str, Any]],
        execution_context: ExecutionContext,
        on_response_delta: Callable[[str], None] | None = None,
    ) -> NOVAState:
        """
        Build the standardized NOVA graph state.
        """

        if not isinstance(
            execution_context,
            ExecutionContext,
        ):
            raise TypeError(
                "execution_context must be an ExecutionContext instance."
            )

        if on_response_delta is not None and not callable(
            on_response_delta
        ):
            raise TypeError(
                "on_response_delta must be callable when provided."
            )

        state: NOVAState = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "user_message": user_message,
            "history": history,
            "understanding": {},
            "plan": {},
            "permission": {
                "allowed": False,
                "requires_confirmation": False,
                "reason": (
                    "Permission check not performed yet."
                ),
            },
            "user_requested": (
                execution_context.user_requested
            ),
            "execution_context": execution_context,
            "confirmation": {
                "id": None,
                "status": None,
                "tool": None,
                "action": None,
                "reason": None,
            },
            "tool_result": {
                "success": False,
                "tool": None,
                "action": None,
                "result": None,
                "error": None,
            },
            "workflow_result": {
                "success": False,
                "status": None,
                "steps": [],
                "error": None,
            },
            "memory_context": "",
            "response": "",
        }

        if on_response_delta is not None:
            state["response_delta_callback"] = on_response_delta

        return state

    def execute(
        self,
        *,
        user_id: str,
        conversation_id: int | None,
        user_message: str,
        history: list[dict[str, Any]],
        execution_context: ExecutionContext,
        on_response_delta: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """
        Execute NOVA's graph using an explicit execution context.
        """

        initial_state = self.build_initial_state(
            user_id=user_id,
            conversation_id=conversation_id,
            user_message=user_message,
            history=history,
            execution_context=execution_context,
            on_response_delta=on_response_delta,
        )

        return self.agent_graph.invoke(
            initial_state
        )

    def execute_autonomous(
        self,
        *,
        user_id: str,
        conversation_id: int | None,
        user_message: str,
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Execute NOVA through the autonomous/background boundary.

        Autonomous callers do not provide an execution context
        themselves. This prevents them from accidentally passing
        interactive permissions.
        """

        return self.execute(
            user_id=user_id,
            conversation_id=conversation_id,
            user_message=user_message,
            history=history,
            execution_context=ExecutionContext.autonomous(),
        )