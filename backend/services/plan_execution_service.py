from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.tool_router import ToolRouter


@dataclass(frozen=True)
class StepExecutionResult:
    """
    Result of one executable plan step.
    """

    step_id: str
    tool: str
    action: str
    status: str
    result: dict[str, Any]
    error: str | None = None


@dataclass(frozen=True)
class PlanExecutionResult:
    """
    Result of an entire multi-step plan execution.

    success:
        True only when every executable step succeeds.

    status:
        completed
        failed
        partial
        blocked

    steps:
        Ordered results for all processed steps.
    """

    success: bool
    status: str
    steps: tuple[StepExecutionResult, ...] = field(
        default_factory=tuple
    )
    error: str | None = None


class PlanExecutionService:
    """
    Execute an already validated multi-step NOVA plan.

    Responsibilities:
    - execute steps in dependency-safe order
    - preserve deterministic execution order
    - record per-step results
    - skip steps whose dependencies failed
    - allow independent steps to continue
    - never perform permission decisions
    - never modify the plan itself

    Permission/confirmation is intentionally handled outside
    this service and will be added at the orchestration layer.
    """

    SUCCESS_STATUSES = {
        "completed",
    }

    FAILURE_STATUSES = {
        "failed",
    }

    SKIPPED_STATUSES = {
        "skipped",
    }

    def __init__(
        self,
        tool_router: ToolRouter | None = None,
    ):
        self.tool_router = (
            tool_router
            if tool_router is not None
            else ToolRouter()
        )

    def execute(
        self,
        *,
        user_id: str,
        steps: list[dict[str, Any]],
    ) -> PlanExecutionResult:
        """
        Execute a validated multi-step plan.

        Each step must have:

            step_id
            tool
            action
            data
            depends_on

        The executor assumes the plan has already passed
        PlannerService validation.

        Defensive validation is still performed so malformed
        input cannot produce undefined execution behavior.
        """

        validation_error = self._validate_input_steps(
            steps
        )

        if validation_error is not None:
            return PlanExecutionResult(
                success=False,
                status="blocked",
                steps=(),
                error=validation_error,
            )

        if not steps:
            return PlanExecutionResult(
                success=True,
                status="completed",
                steps=(),
                error=None,
            )

        normalized_steps = [
            self._normalize_step(step)
            for step in steps
        ]

        pending = {
            step["step_id"]: step
            for step in normalized_steps
        }

        completed_ids: set[str] = set()
        failed_ids: set[str] = set()
        skipped_ids: set[str] = set()

        results: list[StepExecutionResult] = []

        while pending:
            progress_made = False

            for step_id, step in list(
                pending.items()
            ):
                dependencies = set(
                    step["depends_on"]
                )

                if dependencies & (
                    failed_ids
                    | skipped_ids
                ):
                    result = StepExecutionResult(
                        step_id=step["step_id"],
                        tool=step["tool"],
                        action=step["action"],
                        status="skipped",
                        result={},
                        error=(
                            "Step was skipped because "
                            "one or more dependencies "
                            "did not complete successfully."
                        ),
                    )

                    results.append(result)
                    skipped_ids.add(step_id)
                    del pending[step_id]
                    progress_made = True

                    continue

                if not dependencies.issubset(
                    completed_ids
                ):
                    continue

                execution_result = (
                    self._execute_step(
                        user_id=user_id,
                        step=step,
                    )
                )

                results.append(
                    execution_result
                )

                del pending[step_id]
                progress_made = True

                if (
                    execution_result.status
                    == "completed"
                ):
                    completed_ids.add(
                        step_id
                    )
                else:
                    failed_ids.add(
                        step_id
                    )

            if progress_made:
                continue

            unresolved = sorted(
                pending.keys()
            )

            return PlanExecutionResult(
                success=False,
                status="blocked",
                steps=tuple(results),
                error=(
                    "Execution could not make progress. "
                    "Unresolved steps: "
                    f"{', '.join(unresolved)}."
                ),
            )

        if failed_ids or skipped_ids:
            return PlanExecutionResult(
                success=False,
                status="partial",
                steps=tuple(results),
                error=(
                    "One or more plan steps did not "
                    "complete successfully."
                ),
            )

        return PlanExecutionResult(
            success=True,
            status="completed",
            steps=tuple(results),
            error=None,
        )

    def _execute_step(
        self,
        *,
        user_id: str,
        step: dict[str, Any],
    ) -> StepExecutionResult:
        """
        Execute exactly one plan step through the
        central ToolRouter.
        """

        try:
            tool_result = self.tool_router.execute(
                intent=step["tool"],
                user_id=user_id,
                data=step["data"],
            )

        except Exception:
            return StepExecutionResult(
                step_id=step["step_id"],
                tool=step["tool"],
                action=step["action"],
                status="failed",
                result={},
                error="Tool execution failed.",
            )

        if tool_result.get("success") is True:
            return StepExecutionResult(
                step_id=step["step_id"],
                tool=step["tool"],
                action=step["action"],
                status="completed",
                result=dict(
                    tool_result.get(
                        "result"
                    )
                    or {}
                ),
                error=None,
            )

        return StepExecutionResult(
            step_id=step["step_id"],
            tool=step["tool"],
            action=step["action"],
            status="failed",
            result=dict(
                tool_result.get(
                    "result"
                )
                or {}
            ),
            error=(
                tool_result.get("error")
                or "Tool execution failed."
            ),
        )

    def _normalize_step(
        self,
        step: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Normalize a validated step into the internal
        executor representation.
        """

        return {
            "step_id": str(
                step["step_id"]
            ).strip(),
            "tool": str(
                step["tool"]
            ).strip().lower(),
            "action": str(
                step["action"]
            ).strip().lower(),
            "data": dict(
                step.get(
                    "data",
                    {},
                )
            ),
            "depends_on": [
                str(item).strip()
                for item in step.get(
                    "depends_on",
                    [],
                )
            ],
        }

    def _validate_input_steps(
        self,
        steps: Any,
    ) -> str | None:
        """
        Perform defensive executor-level validation.

        PlannerService remains the canonical plan validator,
        but the execution boundary must not trust arbitrary
        input blindly.
        """

        if not isinstance(steps, list):
            return "Execution steps must be provided as a list."

        if not steps:
            return None

        step_ids: set[str] = set()

        for step in steps:
            if not isinstance(step, dict):
                return (
                    "Every execution step must be a dictionary."
                )

            step_id = str(
                step.get(
                    "step_id",
                    "",
                )
            ).strip()

            if not step_id:
                return (
                    "Every execution step must have "
                    "a step ID."
                )

            if step_id in step_ids:
                return (
                    f"Duplicate execution step ID "
                    f"'{step_id}'."
                )

            tool = str(
                step.get(
                    "tool",
                    "",
                )
            ).strip()

            if not tool:
                return (
                    f"Execution step '{step_id}' "
                    "has no tool."
                )

            action = str(
                step.get(
                    "action",
                    "",
                )
            ).strip()

            if not action:
                return (
                    f"Execution step '{step_id}' "
                    "has no action."
                )

            data = step.get(
                "data",
                {},
            )

            if not isinstance(
                data,
                dict,
            ):
                return (
                    f"Execution data for step "
                    f"'{step_id}' must be a dictionary."
                )

            dependencies = step.get(
                "depends_on",
                [],
            )

            if dependencies is None:
                dependencies = []

            if not isinstance(
                dependencies,
                (list, tuple),
            ):
                return (
                    f"Dependencies for execution step "
                    f"'{step_id}' must be a list."
                )

            step_ids.add(
                step_id
            )

        for step in steps:
            step_id = str(
                step["step_id"]
            ).strip()

            dependencies = {
                str(item).strip()
                for item in (
                    step.get(
                        "depends_on",
                        [],
                    )
                    or []
                )
            }

            if step_id in dependencies:
                return (
                    f"Execution step '{step_id}' "
                    "cannot depend on itself."
                )

            unknown = (
                dependencies - step_ids
            )

            if unknown:
                return (
                    f"Execution step '{step_id}' "
                    "depends on unknown step(s): "
                    f"{', '.join(sorted(unknown))}."
                )

        return None