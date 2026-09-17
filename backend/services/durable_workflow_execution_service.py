from __future__ import annotations

from typing import Any

from services.tool_router import ToolRouter
from services.workflow_service import WorkflowService


class DurableWorkflowExecutionService:
    """
    Persistent workflow executor.

    Unlike PlanExecutionService, this executor never treats
    workflow state as temporary in-memory state.

    Every workflow claim, step claim, result, attempt, and
    final status is persisted through WorkflowService.

    This provides the foundation for:
    - resume after partial failure
    - retry failed steps
    - duplicate execution protection
    - process restart recovery
    - future worker/queue execution
    """

    def __init__(
        self,
        workflow_service: WorkflowService | None = None,
        tool_router: ToolRouter | None = None,
    ):
        self.workflow_service = (
            workflow_service
            if workflow_service is not None
            else WorkflowService()
        )

        self.tool_router = (
            tool_router
            if tool_router is not None
            else ToolRouter()
        )

    def execute(
        self,
        *,
        user_id: str,
        workflow_id: int,
    ) -> dict[str, Any]:
        """
        Claim and execute a durable workflow.

        Existing successful steps are never executed again.

        Failed/skipped/blocked steps may execute again when
        their dependencies are now satisfied.
        """

        claimed_workflow = (
            self.workflow_service.claim_workflow(
                user_id=user_id,
                workflow_id=workflow_id,
            )
        )

        if claimed_workflow is None:
            current = (
                self.workflow_service.get_workflow(
                    user_id=user_id,
                    workflow_id=workflow_id,
                )
            )

            if current is None:
                return self._blocked_result(
                    "Workflow was not found."
                )

            if current["status"] == "completed":
                return self._result_from_workflow(
                    current
                )

            if current["status"] == "awaiting_confirmation":
                return self._blocked_result(
                    "Workflow is waiting for user confirmation.",
                    status="awaiting_confirmation",
                    workflow=current,
                )

            if current["status"] == "cancelled":
                return self._blocked_result(
                    "Workflow has been cancelled.",
                    status="cancelled",
                    workflow=current,
                )

            return self._blocked_result(
                "Workflow is already being executed by another worker.",
                status=current["status"],
                workflow=current,
            )

        while True:
            workflow = (
                self.workflow_service.get_workflow(
                    user_id=user_id,
                    workflow_id=workflow_id,
                )
            )

            if workflow is None:
                return self._blocked_result(
                    "Workflow disappeared during execution."
                )

            if workflow["status"] in {
                "completed",
                "failed",
                "partial",
                "blocked",
                "cancelled",
            }:
                return self._result_from_workflow(
                    workflow
                )

            progress_made = False

            step_by_id = {
                step["step_id"]: step
                for step in workflow["steps"]
            }

            for step in workflow["steps"]:
                step_status = step["status"]

                if step_status == "completed":
                    continue

                dependencies = set(
                    step.get("depends_on")
                    or []
                )

                dependency_states = [
                    step_by_id[
                        dependency
                    ]["status"]
                    for dependency in dependencies
                    if dependency in step_by_id
                ]

                if any(
                    status in {
                        "failed",
                        "blocked",
                    }
                    for status in dependency_states
                ):
                    skipped = (
                        self.workflow_service.claim_step(
                            user_id=user_id,
                            workflow_id=workflow_id,
                            step_id=step["step_id"],
                        )
                    )

                    if skipped is None:
                        continue

                    self.workflow_service.finish_step(
                        user_id=user_id,
                        workflow_id=workflow_id,
                        step_id=step["step_id"],
                        status="skipped",
                        result={},
                        error=(
                            "Step was skipped because "
                            "one or more dependencies "
                            "did not complete successfully."
                        ),
                    )

                    self.workflow_service.recalculate_workflow(
                        user_id=user_id,
                        workflow_id=workflow_id,
                    )

                    progress_made = True
                    break

                if any(
                    status == "skipped"
                    for status in dependency_states
                ):
                    skipped = (
                        self.workflow_service.claim_step(
                            user_id=user_id,
                            workflow_id=workflow_id,
                            step_id=step["step_id"],
                        )
                    )

                    if skipped is None:
                        continue

                    self.workflow_service.finish_step(
                        user_id=user_id,
                        workflow_id=workflow_id,
                        step_id=step["step_id"],
                        status="skipped",
                        result={},
                        error=(
                            "Step was skipped because "
                            "a dependency was skipped."
                        ),
                    )

                    self.workflow_service.recalculate_workflow(
                        user_id=user_id,
                        workflow_id=workflow_id,
                    )

                    progress_made = True
                    break

                if not all(
                    status == "completed"
                    for status in dependency_states
                ):
                    continue

                claimed_step = (
                    self.workflow_service.claim_step(
                        user_id=user_id,
                        workflow_id=workflow_id,
                        step_id=step["step_id"],
                    )
                )

                if claimed_step is None:
                    continue

                tool_result = (
                    self._execute_step(
                        user_id=user_id,
                        step=claimed_step,
                    )
                )

                if tool_result["success"] is True:
                    self.workflow_service.finish_step(
                        user_id=user_id,
                        workflow_id=workflow_id,
                        step_id=claimed_step[
                            "step_id"
                        ],
                        status="completed",
                        result=dict(
                            tool_result.get(
                                "result"
                            )
                            or {}
                        ),
                        error=None,
                    )

                else:
                    self.workflow_service.finish_step(
                        user_id=user_id,
                        workflow_id=workflow_id,
                        step_id=claimed_step[
                            "step_id"
                        ],
                        status="failed",
                        result=dict(
                            tool_result.get(
                                "result"
                            )
                            or {}
                        ),
                        error=(
                            tool_result.get(
                                "error"
                            )
                            or "Tool execution failed."
                        ),
                    )

                self.workflow_service.recalculate_workflow(
                    user_id=user_id,
                    workflow_id=workflow_id,
                )

                progress_made = True
                break

            if progress_made:
                continue

            self.workflow_service.recalculate_workflow(
                user_id=user_id,
                workflow_id=workflow_id,
            )

            current = (
                self.workflow_service.get_workflow(
                    user_id=user_id,
                    workflow_id=workflow_id,
                )
            )

            if current is None:
                return self._blocked_result(
                    "Workflow disappeared during execution."
                )

            if current["status"] == "running":
                self._mark_blocked(
                    user_id=user_id,
                    workflow_id=workflow_id,
                )

            return self._result_from_workflow(
                self.workflow_service.get_workflow(
                    user_id=user_id,
                    workflow_id=workflow_id,
                )
            )

    def _execute_step(
        self,
        *,
        user_id: str,
        step: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Execute one claimed step through the central ToolRouter.
        """

        try:
            result = self.tool_router.execute(
                intent=step["tool"],
                user_id=user_id,
                data=dict(
                    step.get("data")
                    or {}
                ),
            )

        except Exception:
            return {
                "success": False,
                "tool": step["tool"],
                "action": step["action"],
                "result": None,
                "error": "Tool execution failed.",
            }

        return {
            "success": (
                result.get("success")
                is True
            ),
            "tool": step["tool"],
            "action": step["action"],
            "result": (
                result.get("result")
                or {}
            ),
            "error": result.get(
                "error"
            ),
        }

    def _mark_blocked(
        self,
        *,
        user_id: str,
        workflow_id: int,
    ) -> None:
        self.workflow_service._transition(
            user_id=user_id,
            workflow_id=workflow_id,
            new_status="blocked",
            allowed_current_statuses={
                "running",
            },
        )

    def _result_from_workflow(
        self,
        workflow: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if workflow is None:
            return self._blocked_result(
                "Workflow result is unavailable."
            )

        result = workflow.get(
            "result"
        )

        if isinstance(result, dict):
            return result

        return {
            "success": (
                workflow["status"]
                == "completed"
            ),
            "status": workflow["status"],
            "workflow_id": workflow["id"],
            "steps": workflow.get(
                "steps",
                [],
            ),
            "error": workflow.get(
                "error"
            ),
        }

    def _blocked_result(
        self,
        error: str,
        *,
        status: str = "blocked",
        workflow: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "status": status,
            "workflow_id": (
                workflow.get("id")
                if workflow
                else None
            ),
            "steps": (
                workflow.get("steps", [])
                if workflow
                else []
            ),
            "error": error,
        }