from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.permission_service import (
    PermissionDecision,
    PermissionService,
)
from services.planner_service import (
    PlanStep,
)


@dataclass(frozen=True)
class StepPermissionDecision:
    """
    Permission result for one plan step.
    """

    step_id: str
    tool: str
    action: str
    allowed: bool
    requires_confirmation: bool
    reason: str


@dataclass(frozen=True)
class PlanPermissionDecision:
    """
    Aggregated permission result for an entire multi-step plan.

    The workflow is evaluated as one authorization boundary.

    Rules:

        Any denied step
            -> entire plan denied

        No denied steps + any confirmation-required step
            -> entire plan requires confirmation

        All steps allowed
            -> entire plan allowed
    """

    allowed: bool
    requires_confirmation: bool
    reason: str
    steps: tuple[StepPermissionDecision, ...] = field(
        default_factory=tuple
    )


class PlanPermissionService:
    """
    Evaluate permission for a multi-step NOVA plan.

    This service does not:
    - execute tools
    - create confirmations
    - modify the database
    - change permissions

    It only combines the existing PermissionService decisions
    into one safe workflow-level decision.

    This all-or-nothing boundary prevents an agentic workflow
    from executing harmless-looking steps before a later
    sensitive step has been authorized.
    """

    def __init__(
        self,
        permission_service: PermissionService | None = None,
    ):
        self.permission_service = (
            permission_service
            if permission_service is not None
            else PermissionService()
        )

    def check(
        self,
        *,
        user_id: str,
        steps: list[PlanStep | dict[str, Any]],
        user_requested: bool,
    ) -> PlanPermissionDecision:
        """
        Evaluate every step in a workflow.

        Existing PermissionService remains the source of truth
        for individual tool/action policy.

        The workflow is denied when any step is denied.

        The workflow requires confirmation when no step is denied
        but at least one step requires confirmation.
        """

        if not isinstance(
            user_requested,
            bool,
        ):
            return self._blocked(
                "Workflow permission requires a boolean "
                "user_requested value."
            )

        if not isinstance(
            steps,
            list,
        ):
            return self._blocked(
                "Workflow steps must be provided as a list."
            )

        if not steps:
            return PlanPermissionDecision(
                allowed=True,
                requires_confirmation=False,
                reason=(
                    "The workflow contains no executable steps."
                ),
                steps=(),
            )

        step_decisions: list[
            StepPermissionDecision
        ] = []

        for raw_step in steps:
            normalized = self._normalize_step(
                raw_step
            )

            if normalized is None:
                return self._blocked(
                    "The workflow contains an invalid plan step."
                )

            step_id = normalized["step_id"]
            tool = normalized["tool"]
            action = normalized["action"]

            decision = self.permission_service.check(
                user_id=user_id,
                tool=tool,
                action=action,
                user_requested=user_requested,
            )

            step_decisions.append(
                StepPermissionDecision(
                    step_id=step_id,
                    tool=tool,
                    action=action,
                    allowed=decision.allowed,
                    requires_confirmation=(
                        decision.requires_confirmation
                    ),
                    reason=decision.reason,
                )
            )

        denied_steps = [
            step
            for step in step_decisions
            if (
                step.allowed is False
                and step.requires_confirmation is False
            )
        ]

        if denied_steps:
            denied_ids = ", ".join(
                step.step_id
                for step in denied_steps
            )

            return PlanPermissionDecision(
                allowed=False,
                requires_confirmation=False,
                reason=(
                    "The workflow is denied because "
                    f"step(s) {denied_ids} are not permitted."
                ),
                steps=tuple(
                    step_decisions
                ),
            )

        confirmation_steps = [
            step
            for step in step_decisions
            if (
                step.allowed is False
                and step.requires_confirmation is True
            )
        ]

        if confirmation_steps:
            confirmation_ids = ", ".join(
                step.step_id
                for step in confirmation_steps
            )

            return PlanPermissionDecision(
                allowed=False,
                requires_confirmation=True,
                reason=(
                    "The workflow requires confirmation "
                    f"for step(s) {confirmation_ids}."
                ),
                steps=tuple(
                    step_decisions
                ),
            )

        return PlanPermissionDecision(
            allowed=True,
            requires_confirmation=False,
            reason=(
                "All steps in the workflow are "
                "permitted to execute."
            ),
            steps=tuple(
                step_decisions
            ),
        )

    def _normalize_step(
        self,
        step: PlanStep | dict[str, Any],
    ) -> dict[str, str] | None:
        """
        Normalize supported step representations.

        PlannerService produces PlanStep objects, while graph
        state uses dictionaries.
        """

        if isinstance(
            step,
            PlanStep,
        ):
            step_id = str(
                step.step_id
            ).strip()

            tool = str(
                step.tool
            ).strip().lower()

            action = str(
                step.action
            ).strip().lower()

        elif isinstance(
            step,
            dict,
        ):
            step_id = str(
                step.get(
                    "step_id",
                    "",
                )
            ).strip()

            tool = str(
                step.get(
                    "tool",
                    "",
                )
            ).strip().lower()

            action = str(
                step.get(
                    "action",
                    "",
                )
            ).strip().lower()

        else:
            return None

        if not step_id:
            return None

        if not tool:
            return None

        if not action:
            return None

        return {
            "step_id": step_id,
            "tool": tool,
            "action": action,
        }

    def _blocked(
        self,
        reason: str,
    ) -> PlanPermissionDecision:
        """
        Return a safe blocked workflow decision.
        """

        return PlanPermissionDecision(
            allowed=False,
            requires_confirmation=False,
            reason=reason,
            steps=(),
        )