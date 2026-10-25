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

        normalized_plan_data, validation_error = (
            self._normalize_and_validate_tool_data(
                tool=tool,
                action=action,
                data=plan_data,
                step_id="step-1",
            )
        )

        if validation_error is not None:
            return PlanDecision(
                requires_tool=False,
                tool=None,
                action=None,
                data={},
                reason=validation_error,
                steps=(),
            )

        plan_data = normalized_plan_data

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

            normalized_data, validation_error = (
                self._normalize_and_validate_tool_data(
                    tool=tool,
                    action=action,
                    data=data,
                    step_id=step_id,
                )
            )

            if validation_error is not None:
                return self._invalid_multi_step_plan(
                    validation_error
                )

            data = normalized_data

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

    def _normalize_and_validate_tool_data(
        self,
        *,
        tool: str,
        action: str,
        data: dict[str, Any],
        step_id: str,
    ) -> tuple[dict[str, Any], str | None]:
        """
        Normalize tool-specific execution data and fail closed
        when a required payload contract is incomplete.

        Web search is normalized here because the understanding
        layer uses web_* field names while ToolRouter consumes
        provider-neutral execution fields.
        """

        normalized = dict(data)

        if tool == "desktop":
            operation = str(normalized.get("desktop_operation") or "").strip().lower()
            target_value = normalized.get("desktop_target")
            target = str(target_value).strip() if target_value is not None else ""
            query_value = normalized.get("desktop_query")
            query = str(query_value).strip() if query_value is not None else ""
            supported_operations = {
                "open_app", "open_url", "search_web", "open_folder", "open_file",
                "find_files", "inspect_screen", "click_ui", "type_ui", "press_key",
                "play_youtube",
            }
            if operation not in supported_operations:
                return normalized, f"Desktop step '{step_id}' uses an unsupported operation."
            if action == "search":
                if operation != "find_files" or not 2 <= len(query) <= 120 or "/" in query or "\\\\" in query:
                    return normalized, f"Desktop file-search step '{step_id}' has an invalid operation or query."
                normalized["desktop_query"] = query
                normalized["desktop_operation"] = operation
                return normalized, None
            if action != "start":
                return normalized, f"Desktop step '{step_id}' must use the start or search action."
            if operation != "inspect_screen" and not target:
                return normalized, f"Desktop step '{step_id}' requires a target."
            maximum_target = {
                "open_app": 80,
                "open_url": 2048,
                "search_web": 500,
                "open_folder": 80,
                "open_file": 180,
                "inspect_screen": 160,
                "click_ui": 160,
                "type_ui": 160,
                "press_key": 32,
                "play_youtube": 180,
            }.get(operation, 0)
            if len(target) > maximum_target or any(ord(char) < 32 for char in target):
                return normalized, f"Desktop step '{step_id}' has a target outside the allowed size or character rules."
            if operation == "play_youtube":
                if target.casefold() in {
                    "song", "songs", "music", "a song", "any song", "something",
                    "anything", "whatever", "that song", "this song", "my favorite song",
                    "my favourite song", "kuch", "koi song", "koi gana", "gaana", "gana", "गाना", "गाने", "गीत", "कोई गाना", "कोई गीत",
                }:
                    return normalized, f"Desktop step '{step_id}' needs a specific YouTube title."
                if len(target) < 2:
                    return normalized, f"Desktop step '{step_id}' needs a specific YouTube title."
            if operation == "type_ui" and (not query or len(query) > 2000):
                return normalized, f"Desktop type step '{step_id}' needs 1–2000 characters of text."
            if operation in {"click_ui", "press_key"} and len(query) > 160:
                return normalized, f"Desktop UI step '{step_id}' has an invalid window hint."
            if operation == "open_url" and not target.lower().startswith(("http://", "https://")):
                return normalized, f"Desktop URL step '{step_id}' must use HTTP(S)."
            normalized["desktop_operation"] = operation
            normalized["desktop_target"] = target or None
            if query_value is not None:
                normalized["desktop_query"] = query
            return normalized, None

        if tool != "web":
            return normalized, None

        if action != "search":
            return (
                normalized,
                (
                    f"Web step '{step_id}' must use "
                    "the 'search' action."
                ),
            )

        query = normalized.get("query")

        if query is None or not str(query).strip():
            return (
                normalized,
                (
                    f"Web search step '{step_id}' "
                    "requires a non-empty query."
                ),
            )

        normalized["query"] = str(query).strip()
        normalized["action"] = "search"
        normalized["web_action"] = "search"

        topic = normalized.get(
            "web_topic",
            normalized.get("topic"),
        )

        if topic is None:
            topic = "general"

        topic = str(topic).strip().lower()

        if topic not in {
            "general",
            "news",
            "finance",
            "weather",
        }:
            return (
                normalized,
                (
                    f"Web search step '{step_id}' "
                    "has an invalid topic."
                ),
            )

        normalized["web_topic"] = topic
        normalized["topic"] = topic

        time_range = normalized.get(
            "web_time_range",
            normalized.get("time_range"),
        )

        if time_range is not None:
            time_range = (
                str(time_range).strip().lower()
            )

            if time_range not in {
                "day",
                "week",
                "month",
                "year",
            }:
                return (
                    normalized,
                    (
                        f"Web search step '{step_id}' "
                        "has an invalid time range."
                    ),
                )

            normalized["web_time_range"] = time_range
            normalized["time_range"] = time_range
        else:
            normalized["web_time_range"] = None
            normalized["time_range"] = None

        max_results = normalized.get(
            "max_results"
        )

        if max_results is not None:
            if isinstance(max_results, bool):
                return (
                    normalized,
                    (
                        f"Web search step '{step_id}' "
                        "has an invalid max_results value."
                    ),
                )

            try:
                max_results = int(max_results)
            except (TypeError, ValueError):
                return (
                    normalized,
                    (
                        f"Web search step '{step_id}' "
                        "has an invalid max_results value."
                    ),
                )

            if not 1 <= max_results <= 10:
                return (
                    normalized,
                    (
                        f"Web search step '{step_id}' "
                        "has an invalid max_results value."
                    ),
                )

            normalized["max_results"] = max_results

        return normalized, None

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
        elif tool == "calendar":
            action = understanding.get("calendar_action")
        elif tool == "web":
            action = understanding.get("web_action") or understanding.get("action")
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

        if tool == "calendar":
            plan_data["calendar_action"] = action