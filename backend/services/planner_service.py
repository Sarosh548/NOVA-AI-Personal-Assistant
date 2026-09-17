from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlanDecision:
    """
    Structured decision produced by NOVA's planner layer.

    The planner does not execute tools.
    It only decides whether a tool is required and,
    if so, which tool/action should be used.
    """

    requires_tool: bool
    tool: str | None
    action: str | None
    data: dict[str, Any]
    reason: str


class PlannerService:
    """
    First-stage planner for NOVA.

    Responsibilities:
    - inspect NOVA's understanding output
    - inspect currently available tool metadata
    - validate the requested tool/action
    - produce a structured plan
    - never execute a tool

    This creates the separation:

        Understanding -> Planner -> ToolRouter

    Future versions can replace or extend the decision logic
    with LLM-based multi-step agentic reasoning.
    """

    def create_plan(
        self,
        understanding: dict[str, Any],
        available_tools: list[dict[str, Any]],
    ) -> PlanDecision:
        """
        Create a structured execution plan from NOVA's
        current understanding and registered tools.
        """

        intent = str(
            understanding.get("intent") or "chat"
        ).strip()

        requires_tool = bool(
            understanding.get("requires_tool")
        )

        if not requires_tool:
            return PlanDecision(
                requires_tool=False,
                tool=None,
                action=None,
                data=dict(understanding),
                reason=(
                    "The current understanding does not "
                    "require an executable tool."
                ),
            )

        tool = intent

        tool_definition = self._find_tool(
            tool_name=tool,
            available_tools=available_tools,
        )

        if tool_definition is None:
            return PlanDecision(
                requires_tool=False,
                tool=None,
                action=None,
                data=dict(understanding),
                reason=(
                    f"The requested tool '{tool}' "
                    "is not currently available."
                ),
            )

        action = self._resolve_action(
            tool=tool,
            understanding=understanding,
            available_actions=tool_definition.get(
                "actions",
                [],
            ),
        )

        if action is None:
            return PlanDecision(
                requires_tool=False,
                tool=None,
                action=None,
                data=dict(understanding),
                reason=(
                    f"No valid action was found for "
                    f"tool '{tool}'."
                ),
            )

        plan_data = dict(understanding)

        self._normalize_plan_fields(
            plan_data=plan_data,
            action=action,
            tool=tool,
        )

        return PlanDecision(
            requires_tool=True,
            tool=tool,
            action=action,
            data=plan_data,
            reason=(
                f"Tool '{tool}' is available and "
                f"action '{action}' is supported."
            ),
        )

    def _find_tool(
        self,
        tool_name: str,
        available_tools: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """
        Find one available tool by name.
        """

        for tool in available_tools:
            if str(
                tool.get("name", "")
            ).strip().lower() == tool_name.lower():
                return tool

        return None

    def _resolve_action(
        self,
        tool: str,
        understanding: dict[str, Any],
        available_actions: list[str],
    ) -> str | None:
        """
        Resolve and validate the action requested by the
        understanding layer.
        """

        normalized_actions = {
            str(action).strip().lower()
            for action in available_actions
            if str(action).strip()
        }

        if tool == "task":
            action = understanding.get("task_action")
        elif tool == "reminder":
            action = understanding.get("reminder_action")
        else:
            action = understanding.get("action")

        if not action:
            return None

        normalized_action = str(
            action
        ).strip().lower()

        if normalized_action not in normalized_actions:
            return None

        return normalized_action

    def _normalize_plan_fields(
        self,
        plan_data: dict[str, Any],
        action: str,
        tool: str,
    ) -> None:
        """
        Normalize the action field so downstream execution
        receives an explicit tool-specific action.
        """

        plan_data["action"] = action
        plan_data["tool"] = tool

        if tool == "task":
            plan_data["task_action"] = action

        if tool == "reminder":
            plan_data["reminder_action"] = action