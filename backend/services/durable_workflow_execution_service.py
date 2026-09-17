from __future__ import annotations

from typing import Any

from services.tool_router import ToolRouter
from services.workflow_service import WorkflowService


class DurableWorkflowExecutionService:
    """
    Persistent workflow executor.

    Every execution call represents one execution attempt.

    Important runtime rule:

        A step is processed at most once per execute() call.

    Therefore a failed step is NOT immediately retried forever
    inside the same execution call. A later execute() call is
    responsible for retry/resume behavior.

    This provides the foundation for:
    - durable state
    - resume after failure
    - explicit retry
    - duplicate execution protection
    - future worker/queue execution
    """

    EXECUTABLE_STATUSES = {
        "pending",
        "failed",
        "blocked",
        "skipped",
    }

    BLOCKING_DEPENDENCY_STATUSES = {
        "failed",
        "blocked",
        "skipped",
    }

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
        Claim and execute one durable workflow run.

        Every step that is eligible at the beginning of this
        invocation may be processed at most once.

        Failed steps are persisted and are retried only when
        execute() is called again.

        Dependent steps are skipped when a dependency fails,
        becomes blocked, or is skipped.
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
                (
                    "Workflow is already being executed "
                    "by another worker."
                ),
                status=current["status"],
                workflow=current,
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

        # -------------------------------------------------
        # Snapshot eligible steps for THIS execution run.
        #
        # A step introduced into an eligible state later in
        # this same execution is not retried automatically.
        # This prevents infinite retry loops.
        # -------------------------------------------------

        eligible_step_ids = {
            step["step_id"]
            for step in current["steps"]
            if step["status"]
            in self.EXECUTABLE_STATUSES
        }

        processed_step_ids: set[str] = set()

        progress_made = True

        while progress_made:
            progress_made = False

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

            step_by_id = {
                step["step_id"]: step
                for step in workflow["steps"]
            }

            for step_id in list(
                eligible_step_ids
            ):
                if step_id in processed_step_ids:
                    continue

                step = step_by_id.get(
                    step_id
                )

                if step is None:
                    processed_step_ids.add(
                        step_id
                    )
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

                # -----------------------------------------
                # Dependency failure/block/skip
                # -----------------------------------------

                if any(
                    status
                    in self.BLOCKING_DEPENDENCY_STATUSES
                    for status in dependency_states
                ):
                    claimed_step = (
                        self.workflow_service.claim_step(
                            user_id=user_id,
                            workflow_id=workflow_id,
                            step_id=step_id,
                        )
                    )

                    if claimed_step is None:
                        processed_step_ids.add(
                            step_id
                        )
                        continue

                    self.workflow_service.finish_step(
                        user_id=user_id,
                        workflow_id=workflow_id,
                        step_id=step_id,
                        status="skipped",
                        result={},
                        error=(
                            "Step was skipped because "
                            "one or more dependencies "
                            "did not complete successfully."
                        ),
                    )

                    processed_step_ids.add(
                        step_id
                    )

                    self.workflow_service.recalculate_workflow(
                        user_id=user_id,
                        workflow_id=workflow_id,
                    )

                    progress_made = True
                    continue

                # -----------------------------------------
                # Wait until all dependencies complete.
                # -----------------------------------------

                if not all(
                    status == "completed"
                    for status in dependency_states
                ):
                    continue

                # -----------------------------------------
                # Claim step atomically.
                # -----------------------------------------

                claimed_step = (
                    self.workflow_service.claim_step(
                        user_id=user_id,
                        workflow_id=workflow_id,
                        step_id=step_id,
                    )
                )

                if claimed_step is None:
                    processed_step_ids.add(
                        step_id
                    )
                    continue

                # -----------------------------------------
                # Execute exactly once in this invocation.
                # -----------------------------------------

                tool_result = self._execute_step(
                    user_id=user_id,
                    step=claimed_step,
                )

                if tool_result["success"] is True:
                    self.workflow_service.finish_step(
                        user_id=user_id,
                        workflow_id=workflow_id,
                        step_id=step_id,
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
                        step_id=step_id,
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

                processed_step_ids.add(
                    step_id
                )

                self.workflow_service.recalculate_workflow(
                    user_id=user_id,
                    workflow_id=workflow_id,
                )

                progress_made = True

            # -------------------------------------------------
            # Loop again only to allow dependencies whose
            # prerequisites completed successfully to run.
            #
            # Already failed/skipped steps remain processed and
            # cannot be retried during this execute() call.
            # -------------------------------------------------

        final_workflow = (
            self.workflow_service.recalculate_workflow(
                user_id=user_id,
                workflow_id=workflow_id,
            )
        )

        if final_workflow is None:
            return self._blocked_result(
                "Workflow result is unavailable."
            )

        return self._result_from_workflow(
            final_workflow
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

        if isinstance(
            result,
            dict,
        ):
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
                workflow.get(
                    "steps",
                    [],
                )
                if workflow
                else []
            ),
            "error": error,
        }