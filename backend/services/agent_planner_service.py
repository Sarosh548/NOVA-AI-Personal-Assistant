from __future__ import annotations

import json
from typing import Any

from services.llm_service import LLMService
from services.planner_service import (
    PlanDecision,
    PlannerService,
)


class AgentPlannerService:
    """
    LLM-powered planning layer for NOVA.

    Responsibilities:
    - understand a potentially multi-action user request
    - ask the LLM to propose structured execution steps
    - restrict planning to currently available tools
    - pass the proposed plan through deterministic validation
    - never execute tools

    Architecture:

        User Message
            ↓
        AgentPlannerService
            ↓
        LLM proposal
            ↓
        PlannerService validation
            ↓
        PlanDecision

    The deterministic PlannerService remains the final
    validation boundary. The LLM is never trusted directly.
    """

    MAX_STEPS = 10

    def __init__(
        self,
        llm_service: LLMService | None = None,
        planner_service: PlannerService | None = None,
    ):
        self.llm_service = (
            llm_service
            if llm_service is not None
            else LLMService()
        )

        self.planner_service = (
            planner_service
            if planner_service is not None
            else PlannerService()
        )

    def create_plan(
        self,
        *,
        user_message: str,
        understanding: dict[str, Any],
        history: list[dict[str, Any]] | None,
        available_tools: list[dict[str, Any]],
    ) -> PlanDecision:
        """
        Ask the LLM to produce a structured multi-step plan
        and validate the result deterministically.

        Any malformed, unsafe, or unsupported LLM plan is
        rejected through PlannerService validation.
        """

        cleaned_message = str(
            user_message
        ).strip()

        if not cleaned_message:
            return self._empty_plan(
                "No user message was provided."
            )

        if not isinstance(
            available_tools,
            list,
        ):
            return self._empty_plan(
                "Available tool metadata is invalid."
            )

        recent_history = (
            history[-10:]
            if history
            else []
        )

        tools_context = self._build_tools_context(
            available_tools
        )

        history_context = self._build_history_context(
            recent_history
        )

        understanding_context = (
            json.dumps(
                understanding,
                ensure_ascii=False,
                default=str,
            )
        )

        instructions = f"""
You are NOVA's execution planning system.

Your job is to convert the CURRENT user request into
a safe, structured execution plan.

You DO NOT execute anything.

You may only use tools and actions listed in the
AVAILABLE TOOLS section.

AVAILABLE TOOLS:
{tools_context}

RECENT CONVERSATION:
{history_context}

CURRENT UNDERSTANDING:
{understanding_context}

CURRENT USER MESSAGE:
{cleaned_message}

Planning rules:

1. Return ONLY valid JSON.
2. Never output markdown.
3. Never invent a tool.
4. Never invent an action.
5. Never use an action that is not listed for its tool.
6. Use the current user request as the primary source.
7. Use recent conversation only when required to resolve
   a reference such as "it", "that task", or "the previous one".
8. Create one step for each distinct executable action.
9. Each step must have:
   - step_id
   - tool
   - action
   - data
   - depends_on
10. step_id values must be unique.
11. Use "step-1", "step-2", "step-3", etc.
12. depends_on must contain only step IDs that already exist
    in the proposed plan.
13. Do not create dependency cycles.
14. Independent actions should normally have an empty
    depends_on list.
15. Only create dependencies when one action genuinely needs
    the result of another.
16. Do not add actions that the user did not request.
17. For normal conversation that requires no executable action,
    return requires_tool=false and steps=[].
18. Do not include explanations outside the JSON.
19. Maximum steps: {self.MAX_STEPS}.

Tool data rules:

For task:
- create:
    data should contain task, priority when available,
    and scheduled_at when available.
- list:
    data should normally be empty.
- start/complete/cancel/delete/update:
    preserve task_id or task_reference when available.
- update:
    preserve priority and/or scheduled_at when requested.

For reminder:
- create:
    data should contain task, scheduled_at when available.
- list:
    data should normally be empty.
- complete/cancel/delete/update:
    preserve reminder_id or reminder_reference when available.
- update:
    preserve task when the reminder text is explicitly changed
    and scheduled_at when the reminder time is changed.

Return exactly this structure:

{{
  "requires_tool": true,
  "steps": [
    {{
      "step_id": "step-1",
      "tool": "task",
      "action": "list",
      "data": {{}},
      "depends_on": []
    }}
  ]
}}

For no executable action:

{{
  "requires_tool": false,
  "steps": []
}}
"""

        try:
            raw_output = (
                self.llm_service
                .generate_with_instructions(
                    instructions=instructions,
                    user_input=cleaned_message,
                )
            )
        except Exception:
            return self._fallback_plan(
                understanding=understanding,
                available_tools=available_tools,
                reason=(
                    "LLM planning failed. "
                    "The request was passed through "
                    "the existing deterministic planner."
                ),
            )

        proposed = self._parse_json(
            raw_output
        )

        if proposed is None:
            return self._fallback_plan(
                understanding=understanding,
                available_tools=available_tools,
                reason=(
                    "The LLM returned an invalid plan. "
                    "The request was passed through "
                    "the existing deterministic planner."
                ),
            )

        if proposed.get(
            "requires_tool"
        ) is False:
            return self._empty_plan(
                "The LLM determined that no executable "
                "tool is required."
            )

        proposed_steps = proposed.get(
            "steps"
        )

        if not isinstance(
            proposed_steps,
            list,
        ):
            return self._empty_plan(
                "The LLM did not return a valid steps list."
            )

        if len(proposed_steps) > self.MAX_STEPS:
            return self._empty_plan(
                f"The proposed plan exceeds the maximum "
                f"of {self.MAX_STEPS} steps."
            )

        return (
            self.planner_service.create_multi_step_plan(
                steps=proposed_steps,
                available_tools=available_tools,
            )
        )

    def _fallback_plan(
        self,
        *,
        understanding: dict[str, Any],
        available_tools: list[dict[str, Any]],
        reason: str,
    ) -> PlanDecision:
        """
        Safely preserve existing deterministic planning behavior
        when LLM-based planning is unavailable or malformed.
        """

        deterministic_plan = (
            self.planner_service.create_plan(
                understanding=understanding,
                available_tools=available_tools,
            )
        )

        if deterministic_plan.requires_tool:
            return deterministic_plan

        return PlanDecision(
            requires_tool=False,
            tool=None,
            action=None,
            data=deterministic_plan.data,
            reason=reason,
            steps=(),
        )

    def _parse_json(
        self,
        raw_output: str,
    ) -> dict[str, Any] | None:
        """
        Parse and minimally validate the LLM's top-level JSON.
        """

        if not raw_output:
            return None

        try:
            parsed = json.loads(
                raw_output.strip()
            )
        except json.JSONDecodeError:
            return None

        if not isinstance(
            parsed,
            dict,
        ):
            return None

        return parsed

    def _build_tools_context(
        self,
        available_tools: list[dict[str, Any]],
    ) -> str:
        """
        Convert tool metadata into a compact planner prompt.
        """

        return json.dumps(
            available_tools,
            ensure_ascii=False,
            indent=2,
        )

    def _build_history_context(
        self,
        history: list[dict[str, Any]],
    ) -> str:
        """
        Convert recent conversation history into planner context.
        """

        if not history:
            return "No previous conversation available."

        lines = []

        for item in history:
            role = str(
                item.get(
                    "role",
                    "unknown",
                )
            )

            content = str(
                item.get(
                    "content",
                    "",
                )
            )

            lines.append(
                f"{role}: {content}"
            )

        return "\n".join(lines)

    def _empty_plan(
        self,
        reason: str,
    ) -> PlanDecision:
        """
        Return a safe non-executable plan.
        """

        return PlanDecision(
            requires_tool=False,
            tool=None,
            action=None,
            data={},
            reason=reason,
            steps=(),
        )