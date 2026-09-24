from __future__ import annotations

from typing import Any

from services.tool_router import ToolRouter
from services.workflow_execution_safety_service import (
    WorkflowExecutionSafetyService,
)
from services.workflow_service import WorkflowService


class DurableWorkflowExecutionService:
    """
    Persistent workflow executor.

    Every execution call represents one execution attempt.

    Important runtime rules:

        A step is processed at most once per execute() call.

        Autonomous workflows are re-checked against the current
        permission/risk policy before any tool execution begins.

        A workflow execution is owned by a durable worker lease.
        The worker must heartbeat before executing each step and
        after external tool execution, before persisting the step
        result.

        All workflow step mutations performed by a lease-aware
        execution are fenced by the workflow claim token.

    Therefore a scheduled workflow cannot execute under stale
    authorization or continue mutating durable state after its
    worker lease has been lost.

    This service provides the foundation for:
    - durable state
    - resume after failure
    - explicit retry
    - duplicate execution protection
    - runtime safety re-check
    - worker leases
    - heartbeat renewal
    - stale-worker fencing
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
        execution_safety_service: (
            WorkflowExecutionSafetyService | None
        ) = None,
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

        self.execution_safety_service = (
            execution_safety_service
            if execution_safety_service is not None
            else WorkflowExecutionSafetyService()
        )

    def execute(
        self,
        *,
        user_id: str,
        workflow_id: int,
    ) -> dict[str, Any]:
        """
        Claim and execute one durable workflow run.

        Autonomous workflows receive a fresh permission/risk
        evaluation after the workflow is atomically claimed for
        execution.

        A successful claim creates a worker lease. The worker
        heartbeats immediately before each step and again after
        external tool execution, before the result is persisted.

        If the worker loses its lease:
        - no new tool execution is started
        - the current step is not finalized
        - no stale worker terminal side effect is claimed
        """

        initial_workflow = (
            self.workflow_service.get_workflow(
                user_id=user_id,
                workflow_id=workflow_id,
            )
        )

        if initial_workflow is None:
            return self._blocked_result(
                "Workflow was not found."
            )

        claimed_workflow = (
            self.workflow_service.claim_workflow(
                user_id=user_id,
                workflow_id=workflow_id,
                expected_current_status=(
                    initial_workflow["status"]
                ),
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
                result = self._result_from_workflow(
                    current
                )
                result[
                    "terminal_effect_owner"
                ] = False
                return result

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

            if current["status"] == "blocked":
                result = self._result_from_workflow(
                    current
                )
                result[
                    "terminal_effect_owner"
                ] = False
                return result

            result = self._blocked_result(
                (
                    "Workflow is already being executed "
                    "by another worker."
                ),
                status=current["status"],
                workflow=current,
            )
            result[
                "terminal_effect_owner"
            ] = False

            return result

        claim_token = claimed_workflow.get(
            "claim_token"
        )

        if not claim_token:
            return self._lease_lost_result(
                workflow=claimed_workflow,
                error=(
                    "Workflow worker lease was not created."
                ),
            )

        # -------------------------------------------------
        # Defense-in-depth safety boundary.
        #
        # Only autonomous/background workflows need this
        # re-check because interactive workflows are already
        # authorized by their interactive execution path.
        #
        # The persisted steps are the source of truth.
        # -------------------------------------------------

        if (
            initial_workflow.get(
                "execution_mode"
            )
            == "autonomous"
        ):
            safety_decision = (
                self.execution_safety_service.check(
                    user_id=user_id,
                    steps=list(
                        initial_workflow.get(
                            "steps",
                            [],
                        )
                    ),
                )
            )

            if (
                safety_decision.allowed
                is not True
            ):
                blocked = (
                    self.workflow_service.block_workflow(
                        user_id=user_id,
                        workflow_id=workflow_id,
                        reason=(
                            "Autonomous workflow was blocked "
                            "by the current execution-time "
                            f"safety policy: "
                            f"{safety_decision.reason}"
                        ),
                        claim_token=claim_token,
                    )
                )

                if blocked is not None:
                    result = self._result_from_workflow(
                        blocked
                    )
                    result[
                        "terminal_effect_owner"
                    ] = True
                    return result

                current = (
                    self.workflow_service.get_workflow(
                        user_id=user_id,
                        workflow_id=workflow_id,
                    )
                )

                return self._lease_lost_result(
                    workflow=current,
                    error=(
                        "Autonomous workflow safety state "
                        "could not be finalized because "
                        "the worker lease was no longer active."
                    ),
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

                # -----------------------------------------
                # The final lease check before any step
                # claim or tool execution.
                # -----------------------------------------

                if not self._heartbeat_workflow(
                    user_id=user_id,
                    workflow_id=workflow_id,
                    claim_token=claim_token,
                ):
                    current = (
                        self.workflow_service.get_workflow(
                            user_id=user_id,
                            workflow_id=workflow_id,
                        )
                    )

                    return self._lease_lost_result(
                        workflow=current,
                        error=(
                            "Workflow worker lease was lost "
                            "before the next step could execute."
                        ),
                    )

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
                            workflow_claim_token=claim_token,
                        )
                    )

                    if claimed_step is None:
                        current = (
                            self.workflow_service.get_workflow(
                                user_id=user_id,
                                workflow_id=workflow_id,
                            )
                        )

                        return self._lease_lost_result(
                            workflow=current,
                            error=(
                                "Workflow worker lease was lost "
                                "before a dependent step could "
                                "be finalized."
                            ),
                        )

                    finished_step = (
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
                            workflow_claim_token=claim_token,
                        )
                    )

                    if finished_step is None:
                        current = (
                            self.workflow_service.get_workflow(
                                user_id=user_id,
                                workflow_id=workflow_id,
                            )
                        )

                        return self._lease_lost_result(
                            workflow=current,
                            error=(
                                "Workflow worker lease was lost "
                                "while finalizing a skipped step."
                            ),
                        )

                    processed_step_ids.add(
                        step_id
                    )

                    recalculated = (
                        self.workflow_service
                        .recalculate_workflow(
                            user_id=user_id,
                            workflow_id=workflow_id,
                            workflow_claim_token=claim_token,
                        )
                    )

                    if recalculated is None:
                        current = (
                            self.workflow_service.get_workflow(
                                user_id=user_id,
                                workflow_id=workflow_id,
                            )
                        )

                        return self._lease_lost_result(
                            workflow=current,
                            error=(
                                "Workflow worker lease was lost "
                                "while recalculating workflow state."
                            ),
                        )

                    if (
                        recalculated["status"]
                        in self.workflow_service
                        .TERMINAL_WORKFLOW_STATUSES
                    ):
                        result = (
                            self._result_from_workflow(
                                recalculated
                            )
                        )
                        result[
                            "terminal_effect_owner"
                        ] = True
                        return result

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
                # Claim step atomically under the workflow
                # lease fence.
                # -----------------------------------------

                claimed_step = (
                    self.workflow_service.claim_step(
                        user_id=user_id,
                        workflow_id=workflow_id,
                        step_id=step_id,
                        workflow_claim_token=claim_token,
                    )
                )

                if claimed_step is None:
                    current = (
                        self.workflow_service.get_workflow(
                            user_id=user_id,
                            workflow_id=workflow_id,
                        )
                    )

                    return self._lease_lost_result(
                        workflow=current,
                        error=(
                            "Workflow worker lease was lost "
                            "before the step could be claimed."
                        ),
                    )

                # -----------------------------------------
                # Execute exactly once in this invocation.
                # -----------------------------------------

                tool_result = self._execute_step(
                    user_id=user_id,
                    step=claimed_step,
                )

                # -----------------------------------------
                # Renew the lease after external execution
                # and before writing the step result.
                #
                # If this fails, the old worker must not
                # finalize a result after ownership was lost.
                # -----------------------------------------

                if not self._heartbeat_workflow(
                    user_id=user_id,
                    workflow_id=workflow_id,
                    claim_token=claim_token,
                ):
                    current = (
                        self.workflow_service.get_workflow(
                            user_id=user_id,
                            workflow_id=workflow_id,
                        )
                    )

                    return self._lease_lost_result(
                        workflow=current,
                        error=(
                            "Workflow worker lease was lost "
                            "after tool execution; the step "
                            "result was not finalized by the "
                            "stale worker."
                        ),
                    )

                if tool_result["success"] is True:
                    finished_step = (
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
                            workflow_claim_token=claim_token,
                        )
                    )

                else:
                    finished_step = (
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
                            workflow_claim_token=claim_token,
                        )
                    )

                if finished_step is None:
                    current = (
                        self.workflow_service.get_workflow(
                            user_id=user_id,
                            workflow_id=workflow_id,
                        )
                    )

                    return self._lease_lost_result(
                        workflow=current,
                        error=(
                            "Workflow worker lease was lost "
                            "while finalizing the step result."
                        ),
                    )

                processed_step_ids.add(
                    step_id
                )

                recalculated = (
                    self.workflow_service
                    .recalculate_workflow(
                        user_id=user_id,
                        workflow_id=workflow_id,
                        workflow_claim_token=claim_token,
                    )
                )

                if recalculated is None:
                    current = (
                        self.workflow_service.get_workflow(
                            user_id=user_id,
                            workflow_id=workflow_id,
                        )
                    )

                    return self._lease_lost_result(
                        workflow=current,
                        error=(
                            "Workflow worker lease was lost "
                            "while recalculating workflow state."
                        ),
                    )

                if (
                    recalculated["status"]
                    in self.workflow_service
                    .TERMINAL_WORKFLOW_STATUSES
                ):
                    result = (
                        self._result_from_workflow(
                            recalculated
                        )
                    )
                    result[
                        "terminal_effect_owner"
                    ] = True
                    return result

                progress_made = True

            # -------------------------------------------------
            # Loop again only to allow dependencies whose
            # prerequisites completed successfully to run.
            #
            # Already failed/skipped steps remain processed and
            # cannot be retried during this execute() call.
            # -------------------------------------------------

        # -------------------------------------------------
        # No terminal state was produced inside the step loop.
        # Recalculate once while the worker still owns the lease.
        # -------------------------------------------------

        final_workflow = (
            self.workflow_service.recalculate_workflow(
                user_id=user_id,
                workflow_id=workflow_id,
                workflow_claim_token=claim_token,
            )
        )

        if final_workflow is None:
            current = (
                self.workflow_service.get_workflow(
                    user_id=user_id,
                    workflow_id=workflow_id,
                )
            )

            return self._lease_lost_result(
                workflow=current,
                error=(
                    "Workflow worker lease was lost before "
                    "the final workflow state was persisted."
                ),
            )

        result = self._result_from_workflow(
            final_workflow
        )
        result[
            "terminal_effect_owner"
        ] = True

        return result

    def _heartbeat_workflow(
        self,
        *,
        user_id: str,
        workflow_id: int,
        claim_token: str,
    ) -> bool:
        """
        Renew the current workflow worker lease.

        A False result means the worker no longer owns an active
        lease and must stop mutating workflow state.
        """

        renewed = (
            self.workflow_service.heartbeat_workflow(
                user_id=user_id,
                workflow_id=workflow_id,
                claim_token=claim_token,
            )
        )

        return renewed is not None

    def _execute_step(
        self,
        *,
        user_id: str,
        step: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Execute one claimed step through the central ToolRouter.
        """

        execution_data = dict(
            step.get("data")
            or {}
        )

        if (
            step.get("tool") == "calendar"
            and step.get("action") == "create"
            and "idempotency_key" not in execution_data
        ):
            workflow_id = step.get("workflow_id")
            step_id = step.get("step_id")

            if workflow_id is not None and step_id:
                execution_data["idempotency_key"] = (
                    f"workflow:{workflow_id}:step:{step_id}"
                )

        try:
            result = self.tool_router.execute(
                intent=step["tool"],
                user_id=user_id,
                data=execution_data,
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

    def _lease_lost_result(
        self,
        *,
        workflow: dict[str, Any] | None,
        error: str,
    ) -> dict[str, Any]:
        """
        Return a non-terminal result for a worker that lost its
        lease.

        The current workflow state remains the durable source of
        truth. Another scheduler/worker may recover or claim it.
        """

        status = (
            workflow.get(
                "status"
            )
            if workflow is not None
            else "running"
        )

        return {
            "success": False,
            "status": status,
            "workflow_id": (
                workflow.get(
                    "id"
                )
                if workflow is not None
                else None
            ),
            "steps": (
                workflow.get(
                    "steps",
                    [],
                )
                if workflow is not None
                else []
            ),
            "error": error,
            "terminal_effect_owner": False,
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