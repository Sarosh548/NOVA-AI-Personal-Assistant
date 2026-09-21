from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.autonomous_workflow_service import (
    AutonomousWorkflowService,
)
from services.permission_service import PermissionService
from services.plan_permission_service import PlanPermissionService
from services.confirmation_service import (
    ConfirmationService,
)
from services.plan_execution_service import (
    PlanExecutionService,
)
from services.tool_router import ToolRouter


@dataclass(frozen=True)
class ConfirmationExecutionResult:
    """
    Result of executing one approved confirmation.

    A successful confirmation is finalized as "consumed".
    An execution failure is finalized as "failed".

    The exact persisted confirmation payload is always used.
    """

    success: bool
    status: str
    confirmation: dict[str, Any] | None
    tool_result: dict[str, Any]
    workflow_result: dict[str, Any]
    error: str | None = None


class ConfirmationExecutionService:
    """
    Canonical executor for approved confirmation records.

    Responsibilities:
    - atomically claim an approved confirmation
    - execute the exact persisted tool/action/data
    - support immediate multi-step workflows
    - support scheduled autonomous workflows
    - finalize confirmation state
    - prevent replay through ConfirmationService.claim_confirmation()

    This service never:
    - accepts replacement execution data
    - re-plans an approved request
    - bypasses confirmation state
    - executes an unapproved confirmation
    """

    DEFAULT_TOOL_RESULT = {
        "success": False,
        "tool": None,
        "action": None,
        "result": None,
        "error": None,
    }

    DEFAULT_WORKFLOW_RESULT = {
        "success": False,
        "status": None,
        "workflow_id": None,
        "scheduled_at": None,
        "steps": [],
        "error": None,
    }

    def __init__(
        self,
        confirmation_service: ConfirmationService | None = None,
        tool_router: ToolRouter | None = None,
        plan_execution_service: (
            PlanExecutionService | None
        ) = None,
        autonomous_workflow_service: (
            AutonomousWorkflowService | None
        ) = None,
        permission_service: PermissionService | None = None,
    ):
        self.confirmation_service = (
            confirmation_service
            if confirmation_service is not None
            else ConfirmationService()
        )

        self.tool_router = (
            tool_router
            if tool_router is not None
            else ToolRouter()
        )

        self.plan_execution_service = (
            plan_execution_service
            if plan_execution_service is not None
            else PlanExecutionService(
                tool_router=self.tool_router
            )
        )

        self.autonomous_workflow_service = (
            autonomous_workflow_service
            if autonomous_workflow_service is not None
            else AutonomousWorkflowService()
        )

        self.permission_service = (
            permission_service
            if permission_service is not None
            else PermissionService()
        )

        self.plan_permission_service = (
            PlanPermissionService(
                permission_service=self.permission_service
            )
        )

    def execute_approved_confirmation(
        self,
        *,
        user_id: str,
        confirmation_id: int,
    ) -> ConfirmationExecutionResult:
        """
        Execute exactly one already-approved confirmation.

        The confirmation is atomically claimed before any
        external/tool execution begins.

        Repeated calls cannot replay the same confirmation.
        """

        claimed = (
            self.confirmation_service.claim_confirmation(
                user_id=user_id,
                confirmation_id=confirmation_id,
            )
        )

        if claimed is None:
            return self._unavailable_result()

        return self._execute_claimed_confirmation(
            user_id=user_id,
            confirmation_id=confirmation_id,
            claimed=claimed,
        )

    def approve_and_execute_confirmation(
        self,
        *,
        user_id: str,
        confirmation_id: int,
    ) -> ConfirmationExecutionResult:
        """
        Atomically approve and execute one pending confirmation.

        The confirmation service performs the database transition:

            pending -> processing

        before any external/tool execution begins.

        Repeated calls cannot replay the same confirmation.
        """

        claimed = (
            self.confirmation_service
            .approve_and_claim_confirmation(
                user_id=user_id,
                confirmation_id=confirmation_id,
            )
        )

        if claimed is None:
            return self._unavailable_result()

        return self._execute_claimed_confirmation(
            user_id=user_id,
            confirmation_id=confirmation_id,
            claimed=claimed,
        )

    def _unavailable_result(
        self,
    ) -> ConfirmationExecutionResult:
        return ConfirmationExecutionResult(
            success=False,
            status="unavailable",
            confirmation=None,
            tool_result=dict(
                self.DEFAULT_TOOL_RESULT
            ),
            workflow_result=dict(
                self.DEFAULT_WORKFLOW_RESULT
            ),
            error=(
                "This confirmation is no longer "
                "available for execution."
            ),
        )

    def _execute_claimed_confirmation(
        self,
        *,
        user_id: str,
        confirmation_id: int,
        claimed: dict[str, Any],
    ) -> ConfirmationExecutionResult:
        data = claimed.get(
            "data"
        )

        if not isinstance(
            data,
            dict,
        ):
            return self._finish_failure(
                user_id=user_id,
                confirmation_id=confirmation_id,
                claimed=claimed,
                error=(
                    "The saved confirmation data "
                    "is invalid."
                ),
            )

        if (
            claimed.get("tool")
            == "workflow"
            and claimed.get("action")
            == "execute"
        ):
            return self._execute_workflow(
                user_id=user_id,
                confirmation_id=confirmation_id,
                claimed=claimed,
                data=data,
            )

        return self._execute_tool(
            user_id=user_id,
            confirmation_id=confirmation_id,
            claimed=claimed,
            data=data,
        )


    def _check_tool_safety(
        self,
        *,
        user_id: str,
        tool: str,
        action: str,
        data: dict[str, Any],
    ) -> str | None:
        decision = self.permission_service.check(
            user_id=user_id,
            tool=tool,
            action=action,
            user_requested=True,
            data=data,
        )

        if (
            not decision.allowed
            and not decision.requires_confirmation
        ):
            return (
                "The action is no longer permitted under "
                "the current authorization policy."
            )

        return None

    def _check_workflow_safety(
        self,
        *,
        user_id: str,
        steps: Any,
    ) -> str | None:
        if not isinstance(steps, list):
            return None

        decision = self.plan_permission_service.check(
            user_id=user_id,
            steps=list(steps),
            user_requested=True,
        )

        if (
            not decision.allowed
            and not decision.requires_confirmation
        ):
            return (
                "The workflow is no longer permitted under "
                "the current authorization policy."
            )

        return None

    def _execute_tool(
        self,
        *,
        user_id: str,
        confirmation_id: int,
        claimed: dict[str, Any],
        data: dict[str, Any],
    ) -> ConfirmationExecutionResult:
        tool_name = str(
            claimed.get("tool")
            or ""
        ).strip().lower()

        action = str(
            claimed.get("action")
            or ""
        ).strip().lower()

        if not tool_name:
            return self._finish_failure(
                user_id=user_id,
                confirmation_id=confirmation_id,
                claimed=claimed,
                error="The saved confirmation tool is missing.",
            )

        if not action:
            return self._finish_failure(
                user_id=user_id,
                confirmation_id=confirmation_id,
                claimed=claimed,
                error="The saved confirmation action is missing.",
            )

        safety_error = self._check_tool_safety(
            user_id=user_id,
            tool=tool_name,
            action=action,
            data=data,
        )

        if safety_error is not None:
            return self._finish_failure(
                user_id=user_id,
                confirmation_id=confirmation_id,
                claimed=claimed,
                error=safety_error,
            )

        try:
            tool_result = self.tool_router.execute(
                intent=tool_name,
                user_id=user_id,
                data=dict(data),
            )

        except Exception:
            tool_result = {
                "success": False,
                "tool": tool_name,
                "action": action,
                "result": None,
                "error": "Tool execution failed.",
            }

        success = (
            tool_result.get("success")
            is True
        )

        finished = (
            self.confirmation_service.finish_confirmation(
                user_id=user_id,
                confirmation_id=confirmation_id,
                success=success,
                claim_token=claimed.get("claim_token"),
            )
        )

        confirmation = (
            finished
            if finished is not None
            else claimed
        )

        return ConfirmationExecutionResult(
            success=success,
            status=(
                "completed"
                if success
                else "failed"
            ),
            confirmation=confirmation,
            tool_result=tool_result,
            workflow_result=dict(
                self.DEFAULT_WORKFLOW_RESULT
            ),
            error=(
                None
                if success
                else tool_result.get(
                    "error"
                )
            ),
        )

    def _execute_workflow(
        self,
        *,
        user_id: str,
        confirmation_id: int,
        claimed: dict[str, Any],
        data: dict[str, Any],
    ) -> ConfirmationExecutionResult:
        execution_mode = str(
            data.get("execution_mode")
            or "workflow"
        ).strip().lower()

        steps = data.get(
            "steps",
            [],
        )

        safety_error = self._check_workflow_safety(
            user_id=user_id,
            steps=steps,
        )

        if safety_error is not None:
            return self._finish_workflow_failure(
                user_id=user_id,
                confirmation_id=confirmation_id,
                claimed=claimed,
                error=safety_error,
            )

        if execution_mode == "autonomous":
            return self._schedule_autonomous_workflow(
                user_id=user_id,
                confirmation_id=confirmation_id,
                claimed=claimed,
                data=data,
                steps=steps,
            )

        return self._execute_immediate_workflow(
            user_id=user_id,
            confirmation_id=confirmation_id,
            claimed=claimed,
            steps=steps,
        )

    def _execute_immediate_workflow(
        self,
        *,
        user_id: str,
        confirmation_id: int,
        claimed: dict[str, Any],
        steps: Any,
    ) -> ConfirmationExecutionResult:
        if not isinstance(
            steps,
            list,
        ):
            return self._finish_workflow_failure(
                user_id=user_id,
                confirmation_id=confirmation_id,
                claimed=claimed,
                error=(
                    "The saved workflow steps "
                    "are invalid."
                ),
            )

        try:
            execution = (
                self.plan_execution_service.execute(
                    user_id=user_id,
                    steps=list(steps),
                )
            )
        except Exception:
            return self._finish_workflow_failure(
                user_id=user_id,
                confirmation_id=confirmation_id,
                claimed=claimed,
                error=(
                    "Workflow execution failed."
                ),
            )

        workflow_result = {
            "success": execution.success,
            "status": execution.status,
            "workflow_id": None,
            "scheduled_at": None,
            "steps": [
                {
                    "step_id": step.step_id,
                    "tool": step.tool,
                    "action": step.action,
                    "status": step.status,
                    "result": dict(
                        step.result
                    ),
                    "error": step.error,
                }
                for step in execution.steps
            ],
            "error": execution.error,
        }

        finished = (
            self.confirmation_service.finish_confirmation(
                user_id=user_id,
                confirmation_id=confirmation_id,
                success=execution.success,
                claim_token=claimed.get("claim_token"),
            )
        )

        confirmation = (
            finished
            if finished is not None
            else claimed
        )

        return ConfirmationExecutionResult(
            success=execution.success,
            status=execution.status,
            confirmation=confirmation,
            tool_result=dict(
                self.DEFAULT_TOOL_RESULT
            ),
            workflow_result=workflow_result,
            error=execution.error,
        )

    def _schedule_autonomous_workflow(
        self,
        *,
        user_id: str,
        confirmation_id: int,
        claimed: dict[str, Any],
        data: dict[str, Any],
        steps: Any,
    ) -> ConfirmationExecutionResult:
        if not isinstance(
            steps,
            list,
        ):
            return self._finish_workflow_failure(
                user_id=user_id,
                confirmation_id=confirmation_id,
                claimed=claimed,
                error=(
                    "The saved autonomous workflow "
                    "steps are invalid."
                ),
            )

        scheduled_at = data.get(
            "scheduled_at"
        )

        if scheduled_at is None:
            return self._finish_workflow_failure(
                user_id=user_id,
                confirmation_id=confirmation_id,
                claimed=claimed,
                error=(
                    "The saved autonomous workflow "
                    "schedule is missing."
                ),
            )

        plan = {
            "requires_tool": True,
            "execution_mode": "autonomous",
            "tool": None,
            "action": None,
            "data": dict(data),
            "scheduled_at": scheduled_at,
            "reason": (
                "Autonomous workflow approved through "
                "a persisted confirmation."
            ),
            "steps": list(steps),
        }

        try:
            workflow = (
                self.autonomous_workflow_service
                .create_scheduled_workflow(
                    user_id=user_id,
                    conversation_id=(
                        claimed.get(
                            "conversation_id"
                        )
                    ),
                    plan=plan,
                    steps=list(steps),
                    scheduled_at=scheduled_at,
                    idempotency_key=(
                        f"confirmation:{confirmation_id}"
                    ),
                )
            )

        except Exception as exc:
            return self._finish_workflow_failure(
                user_id=user_id,
                confirmation_id=confirmation_id,
                claimed=claimed,
                error=str(exc),
            )

        workflow_result = {
            "success": True,
            "status": "scheduled",
            "workflow_id": workflow["id"],
            "scheduled_at": workflow[
                "scheduled_at"
            ],
            "steps": [],
            "error": None,
        }

        finished = (
            self.confirmation_service.finish_confirmation(
                user_id=user_id,
                confirmation_id=confirmation_id,
                success=True,
                claim_token=claimed.get("claim_token"),
            )
        )

        confirmation = (
            finished
            if finished is not None
            else claimed
        )

        return ConfirmationExecutionResult(
            success=True,
            status="scheduled",
            confirmation=confirmation,
            tool_result=dict(
                self.DEFAULT_TOOL_RESULT
            ),
            workflow_result=workflow_result,
            error=None,
        )

    def _finish_failure(
        self,
        *,
        user_id: str,
        confirmation_id: int,
        claimed: dict[str, Any],
        error: str,
    ) -> ConfirmationExecutionResult:
        finished = (
            self.confirmation_service.finish_confirmation(
                user_id=user_id,
                confirmation_id=confirmation_id,
                success=False,
                claim_token=claimed.get("claim_token"),
            )
        )

        confirmation = (
            finished
            if finished is not None
            else claimed
        )

        tool_result = {
            "success": False,
            "tool": claimed.get("tool"),
            "action": claimed.get("action"),
            "result": None,
            "error": error,
        }

        return ConfirmationExecutionResult(
            success=False,
            status="failed",
            confirmation=confirmation,
            tool_result=tool_result,
            workflow_result=dict(
                self.DEFAULT_WORKFLOW_RESULT
            ),
            error=error,
        )

    def _finish_workflow_failure(
        self,
        *,
        user_id: str,
        confirmation_id: int,
        claimed: dict[str, Any],
        error: str,
    ) -> ConfirmationExecutionResult:
        finished = (
            self.confirmation_service.finish_confirmation(
                user_id=user_id,
                confirmation_id=confirmation_id,
                success=False,
                claim_token=claimed.get("claim_token"),
            )
        )

        confirmation = (
            finished
            if finished is not None
            else claimed
        )

        workflow_result = {
            **self.DEFAULT_WORKFLOW_RESULT,
            "status": "failed",
            "error": error,
        }

        return ConfirmationExecutionResult(
            success=False,
            status="failed",
            confirmation=confirmation,
            tool_result=dict(
                self.DEFAULT_TOOL_RESULT
            ),
            workflow_result=workflow_result,
            error=error,
        )