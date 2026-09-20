from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlanStep:
    """
    One executable step inside NOVA's future multi-step plan.

    A step describes what NOVA intends to execute.
    It does not execute anything itself.

    step_id:
        Stable identifier within the current plan.

    tool:
        Registered NOVA tool name.

    action:
        Action supported by that tool.

    data:
        Exact input payload required by the tool.

    depends_on:
        Step IDs that must complete before this step can run.
    """

    step_id: str
    tool: str
    action: str
    data: dict[str, Any]
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanDecision:
    """
    Structured decision produced by NOVA's planner layer.

    The planner does not execute tools.
    It only decides whether a tool is required and,
    if so, which tool/action should be used.

    `steps` introduces the multi-step planning contract
    while preserving the existing single-step fields for
    backward compatibility.
    """

    requires_tool: bool
    tool: str | None
    action: str | None
    data: dict[str, Any]
    reason: str
    steps: tuple[PlanStep, ...] = ()


class PlannerService:
    """
    Planner layer for NOVA.

    Responsibilities:
    - inspect NOVA's understanding output
    - inspect currently available tool metadata
    - validate requested tools/actions
    - produce structured execution plans
    - validate multi-step dependencies
    - never execute tools

    Current single-step behavior:

        Understanding -> one validated PlanStep

    Multi-step planning contract:

        Multiple requested steps
            -> validate tools/actions
            -> validate dependencies
            -> reject invalid/cyclic plans
            -> return validated PlanSteps

    Actual multi-step execution will be handled by a
    separate execution layer later.
    """

    def create_plan(
        self,
        understanding: dict[str, Any],
        available_tools: list[dict[str, Any]],
    ) -> PlanDecision:
        """
        Create a structured single-step execution plan from
        NOVA's current understanding and registered tools.

        Existing NOVA behavior is intentionally preserved.
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
                steps=(),
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
                steps=(),
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
                steps=(),
            )

        plan_data = dict(understanding)

        self._normalize_plan_fields(
            plan_data=plan_data,
            action=action,
            tool=tool,
        )

        step = PlanStep(
            step_id="step-1",
            tool=tool,
            action=action,
            data=dict(plan_data),
            depends_on=(),
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
            steps=(step,),
        )

    def create_multi_step_plan(
        self,
        steps: list[dict[str, Any]],
        available_tools: list[dict[str, Any]],
    ) -> PlanDecision:
        """
        Validate and build a multi-step execution plan.

        This method does not execute anything.

        Expected input shape:

            [
                {
                    "step_id": "step-1",
                    "tool": "task",
                    "action": "list",
                    "data": {...},
                    "depends_on": [],
                },
                {
                    "step_id": "step-2",
                    "tool": "reminder",
                    "action": "create",
                    "data": {...},
                    "depends_on": ["step-1"],
                },
            ]

        Validation includes:
        - non-empty plan
        - valid step structure
        - unique step IDs
        - valid registered tools
        - supported actions
        - dictionary payloads
        - valid dependency references
        - no self-dependencies
        - no duplicate dependencies
        - no dependency cycles
        """

        if not isinstance(steps, list) or not steps:
            return self._invalid_multi_step_plan(
                "The multi-step plan must contain at least one step."
            )

        normalized_steps: list[PlanStep] = []
        step_ids: set[str] = set()

        for raw_step in steps:
            if not isinstance(raw_step, dict):
                return self._invalid_multi_step_plan(
                    "Every plan step must be a dictionary."
                )

            step_id = str(
                raw_step.get("step_id", "")
            ).strip()

            if not step_id:
                return self._invalid_multi_step_plan(
                    "Every plan step must have a step ID."
                )

            if step_id in step_ids:
                return self._invalid_multi_step_plan(
                    f"Duplicate plan step ID '{step_id}'."
                )

            tool = str(
                raw_step.get("tool", "")
            ).strip().lower()

            if not tool:
                return self._invalid_multi_step_plan(
                    f"Plan step '{step_id}' has no tool."
                )

            tool_definition = self._find_tool(
                tool_name=tool,
                available_tools=available_tools,
            )

            if tool_definition is None:
                return self._invalid_multi_step_plan(
                    f"The requested tool '{tool}' "
                    f"for step '{step_id}' "
                    "is not currently available."
                )

            action = str(
                raw_step.get("action", "")
            ).strip().lower()

            if not action:
                return self._invalid_multi_step_plan(
                    f"Plan step '{step_id}' has no action."
                )

            available_actions = tool_definition.get(
                "actions",
                [],
            )

            normalized_actions = {
                str(item).strip().lower()
                for item in available_actions
                if str(item).strip()
            }

            if action not in normalized_actions:
                return self._invalid_multi_step_plan(
                    f"Action '{action}' is not supported "
                    f"by tool '{tool}' for step '{step_id}'."
                )

            data = raw_step.get(
                "data",
                {},
            )

            if not isinstance(data, dict):
                return self._invalid_multi_step_plan(
                    f"Data for plan step '{step_id}' "
                    "must be a dictionary."
                )

            raw_dependencies = raw_step.get(
                "depends_on",
                [],
            )

            if raw_dependencies is None:
                raw_dependencies = []

            if not isinstance(
                raw_dependencies,
                (list, tuple),
            ):
                return self._invalid_multi_step_plan(
                    f"Dependencies for plan step "
                    f"'{step_id}' must be a list."
                )

            dependencies = tuple(
                str(item).strip()
                for item in raw_dependencies
                if str(item).strip()
            )

            if len(dependencies) != len(
                set(dependencies)
            ):
                return self._invalid_multi_step_plan(
                    f"Plan step '{step_id}' contains "
                    "duplicate dependencies."
                )

            if step_id in dependencies:
                return self._invalid_multi_step_plan(
                    f"Plan step '{step_id}' cannot "
                    "depend on itself."
                )

            step_ids.add(step_id)

            normalized_steps.append(
                PlanStep(
                    step_id=step_id,
                    tool=tool,
                    action=action,
                    data=dict(data),
                    depends_on=dependencies,
                )
            )

        validation_error = (
            self._validate_dependencies(
                normalized_steps
            )
        )

        if validation_error is not None:
            return self._invalid_multi_step_plan(
                validation_error
            )

        plan_data = {
            "steps": [
                {
                    "step_id": step.step_id,
                    "tool": step.tool,
                    "action": step.action,
                    "data": dict(step.data),
                    "depends_on": list(
                        step.depends_on
                    ),
                }
                for step in normalized_steps
            ]
        }

        first_step = normalized_steps[0]

        if len(normalized_steps) == 1:
            legacy_tool = first_step.tool
            legacy_action = first_step.action
            legacy_data = dict(first_step.data)
        else:
            legacy_tool = None
            legacy_action = None
            legacy_data = plan_data

        return PlanDecision(
            requires_tool=True,
            tool=legacy_tool,
            action=legacy_action,
            data=legacy_data,
            reason=(
                f"Validated {len(normalized_steps)} "
                "executable plan step(s)."
            ),
            steps=tuple(normalized_steps),
        )

    def _invalid_multi_step_plan(
        self,
        reason: str,
    ) -> PlanDecision:
        """
        Return a safe non-executable result for an invalid
        multi-step plan.
        """

        return PlanDecision(
            requires_tool=False,
            tool=None,
            action=None,
            data={},
            reason=reason,
            steps=(),
        )

    def _validate_dependencies(
        self,
        steps: list[PlanStep],
    ) -> str | None:
        """
        Validate dependency references and detect cycles.

        Returns:
            None when the dependency graph is valid.
            A human-readable error otherwise.
        """

        step_ids = {
            step.step_id
            for step in steps
        }

        dependencies = {
            step.step_id: set(
                step.depends_on
            )
            for step in steps
        }

        for step in steps:
            for dependency in step.depends_on:
                if dependency not in step_ids:
                    return (
                        f"Plan step '{step.step_id}' "
                        f"depends on unknown step "
                        f"'{dependency}'."
                    )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> bool:
            if step_id in visiting:
                return False

            if step_id in visited:
                return True

            visiting.add(step_id)

            for dependency in dependencies[
                step_id
            ]:
                if not visit(dependency):
                    return False

            visiting.remove(step_id)
            visited.add(step_id)

            return True

        for step_id in step_ids:
            if not visit(step_id):
                return (
                    "The multi-step plan contains "
                    "a dependency cycle."
                )

        return None

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
        elif tool == "email":
            action = understanding.get("email_action") or understanding.get("action")
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