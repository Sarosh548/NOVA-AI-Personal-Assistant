from __future__ import annotations

import asyncio
import logging
from typing import Any

from services.activity_event_service import (
    ActivityEventService,
)
from services.durable_workflow_execution_service import (
    DurableWorkflowExecutionService,
)
from services.notification_service import NotificationService
from services.workflow_service import WorkflowService


logger = logging.getLogger(__name__)


class AutonomousWorkflowScheduler:
    """
    Background scheduler for durable autonomous workflows.

    Responsibilities:
    - recover stale autonomous workflows whose worker leases
      have expired
    - poll for due autonomous workflows
    - delegate execution to the durable execution service
    - record durable terminal activity events
    - notify the user when autonomous execution reaches
      a terminal state

    Does not:
    - execute tools directly
    - bypass permission checks
    - modify workflow plans
    - retry failed workflows automatically

    The persistent workflow remains the source of truth.
    """

    TERMINAL_STATUSES = {
        "completed",
        "partial",
        "failed",
        "blocked",
    }

    def __init__(
        self,
        interval_seconds: int = 5,
        workflow_service: WorkflowService | None = None,
        execution_service: DurableWorkflowExecutionService | None = None,
        notification_service: NotificationService | None = None,
        activity_event_service: (
            ActivityEventService | None
        ) = None,
        batch_size: int = 20,
    ):
        if interval_seconds < 1:
            raise ValueError(
                "interval_seconds must be at least 1"
            )

        if batch_size < 1:
            raise ValueError(
                "batch_size must be at least 1"
            )

        self.interval_seconds = interval_seconds

        self.workflow_service = (
            workflow_service
            if workflow_service is not None
            else WorkflowService()
        )

        self.execution_service = (
            execution_service
            if execution_service is not None
            else DurableWorkflowExecutionService(
                workflow_service=self.workflow_service
            )
        )

        self.notification_service = (
            notification_service
            if notification_service is not None
            else NotificationService()
        )

        workflow_engine = getattr(
            self.workflow_service,
            "engine",
            None,
        )

        self.activity_event_service = (
            activity_event_service
            if activity_event_service is not None
            else ActivityEventService(
                db_engine=workflow_engine
            )
        )

        self.batch_size = batch_size
        self._running = False

    async def process_due_workflows(self) -> None:
        """
        Recover stale workers first, then process the currently
        due autonomous workflow queue.

        A recovered stale workflow is returned to pending by
        WorkflowService and can therefore be selected immediately
        by list_due_autonomous_workflows().
        """

        try:
            self.workflow_service.recover_stale_autonomous_workflows(
                limit=self.batch_size
            )
        except Exception:
            logger.exception(
                "Could not recover stale autonomous workflows."
            )

        workflows = (
            self.workflow_service
            .list_due_autonomous_workflows(
                limit=self.batch_size
            )
        )

        for workflow in workflows:
            workflow_id = workflow["id"]
            user_id = workflow["user_id"]

            try:
                result = (
                    self.execution_service.execute(
                        user_id=user_id,
                        workflow_id=workflow_id,
                    )
                )

                if (
                    result.get(
                        "terminal_effect_owner",
                        True,
                    )
                    is not True
                ):
                    continue

                self._record_terminal_event(
                    workflow=workflow,
                    result=result,
                )

                self._notify_terminal_result(
                    workflow=workflow,
                    result=result,
                )

            except Exception:
                logger.exception(
                    "Autonomous workflow %s failed outside "
                    "normal execution handling.",
                    workflow_id,
                )

    def _record_terminal_event(
        self,
        *,
        workflow: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        status = result.get(
            "status"
        )

        if status not in self.TERMINAL_STATUSES:
            return

        event_status = {
            "completed": "success",
            "partial": "partial",
            "failed": "failed",
            "blocked": "blocked",
        }[status]

        event_type = (
            f"workflow_{status}"
        )

        title = {
            "completed": (
                "Autonomous workflow completed"
            ),
            "partial": (
                "Autonomous workflow partially completed"
            ),
            "failed": (
                "Autonomous workflow failed"
            ),
            "blocked": (
                "Autonomous workflow blocked"
            ),
        }[status]

        summary = {
            "completed": (
                "NOVA completed an autonomous background workflow."
            ),
            "partial": (
                "NOVA completed an autonomous workflow with "
                "some unsuccessful steps."
            ),
            "failed": (
                "NOVA attempted an autonomous workflow, "
                "but execution failed."
            ),
            "blocked": (
                "NOVA blocked an autonomous workflow because "
                "it was not permitted to execute."
            ),
        }[status]

        workflow_id = (
            result.get("workflow_id")
            or workflow.get("id")
        )

        try:
            self.activity_event_service.record_event(
                user_id=workflow["user_id"],
                conversation_id=workflow.get(
                    "conversation_id"
                ),
                workflow_id=workflow_id,
                event_type=event_type,
                source="autonomous_workflow",
                status=event_status,
                title=title,
                summary=summary,
                metadata={
                    "workflow_id": workflow_id,
                    "status": status,
                    "execution_mode": (
                        workflow.get(
                            "execution_mode"
                        )
                    ),
                    "scheduled_at": (
                        workflow.get(
                            "scheduled_at"
                        )
                    ),
                    "error": result.get(
                        "error"
                    ),
                },
            )
        except Exception:
            logger.exception(
                "Could not record terminal activity event "
                "for autonomous workflow %s.",
                workflow_id,
            )

    def _notify_terminal_result(
        self,
        *,
        workflow: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        status = result.get("status")

        if status not in self.TERMINAL_STATUSES:
            return

        workflow_id = (
            result.get("workflow_id")
            or workflow.get("id")
        )

        if status == "completed":
            title = "NOVA completed a background task"
            body = (
                f"Autonomous workflow #{workflow_id} "
                "completed successfully."
            )

        elif status == "partial":
            title = "NOVA partially completed a background task"
            body = (
                f"Autonomous workflow #{workflow_id} "
                "completed with some steps that did not succeed."
            )

        elif status == "failed":
            title = "NOVA background task failed"
            body = (
                f"Autonomous workflow #{workflow_id} failed."
            )

        else:
            title = "NOVA background task was blocked"
            body = (
                f"Autonomous workflow #{workflow_id} was blocked."
            )

        try:
            self.notification_service.notify(
                user_id=workflow["user_id"],
                title=title,
                body=body,
                notification_type="workflow",
                metadata={
                    "workflow_id": workflow_id,
                    "status": status,
                },
            )

        except Exception:
            logger.exception(
                "Could not notify user about autonomous "
                "workflow %s.",
                workflow_id,
            )

    async def run(self) -> None:
        if self._running:
            return

        self._running = True

        logger.info(
            "NOVA autonomous workflow scheduler started "
            "(interval=%ss, batch=%s)",
            self.interval_seconds,
            self.batch_size,
        )

        try:
            while self._running:
                await self.process_due_workflows()
                await asyncio.sleep(
                    self.interval_seconds
                )

        finally:
            self._running = False

            logger.info(
                "NOVA autonomous workflow scheduler stopped."
            )

    def stop(self) -> None:
        self._running = False