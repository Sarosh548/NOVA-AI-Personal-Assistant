from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.plan_permission_service import (
    PlanPermissionService,
)


@dataclass(frozen=True)
class WorkflowExecutionSafetyDecision:
    """
    Current authorization result for a persisted workflow.

    allowed:
        The workflow may continue to execution.

    requires_confirmation:
        The workflow is not currently executable without
        explicit user approval.

    reason:
        Human-readable explanation.

    risk_levels:
        Current risk level for each workflow step.

    risk_flags:
        Deterministic risk flags found for each workflow step.
    """

    allowed: bool
    requires_confirmation: bool
    reason: str
    risk_levels: dict[str, str]
    risk_flags: dict[str, tuple[str, ...]]


class WorkflowExecutionSafetyService:
    """
    Re-check authorization immediately before autonomous execution.

    This is a defense-in-depth layer.

    It does NOT:
    - execute tools
    - modify permissions
    - modify workflow state
    - create confirmations
    """

    def __init__(
        self,
        plan_permission_service: PlanPermissionService | None = None,
    ):
        self.plan_permission_service = (
            plan_permission_service
            if plan_permission_service is not None
            else PlanPermissionService()
        )

    def check(
        self,
        *,
        user_id: str,
        steps: list[dict[str, Any]],
    ) -> WorkflowExecutionSafetyDecision:
        """
        Re-evaluate every persisted workflow step using
        autonomous/background authority semantics.

        user_requested is intentionally always False here.

        This means a workflow cannot gain interactive authority
        merely because it was originally created interactively.
        """

        if not str(user_id).strip():
            return WorkflowExecutionSafetyDecision(
                allowed=False,
                requires_confirmation=False,
                reason="Workflow user_id is missing.",
                risk_levels={},
                risk_flags={},
            )

        if not isinstance(
            steps,
            list,
        ):
            return WorkflowExecutionSafetyDecision(
                allowed=False,
                requires_confirmation=False,
                reason="Workflow steps must be provided as a list.",
                risk_levels={},
                risk_flags={},
            )

        decision = self.plan_permission_service.check(
            user_id=str(user_id).strip(),
            steps=steps,
            user_requested=False,
        )

        risk_levels = {
            step.step_id: step.risk_level
            for step in decision.steps
        }

        risk_flags = {
            step.step_id: tuple(
                step.risk_flags
            )
            for step in decision.steps
        }

        return WorkflowExecutionSafetyDecision(
            allowed=decision.allowed,
            requires_confirmation=(
                decision.requires_confirmation
            ),
            reason=decision.reason,
            risk_levels=risk_levels,
            risk_flags=risk_flags,
        )