from __future__ import annotations

import asyncio
import logging
from typing import Any

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
    - poll for due autonomous workflows
    - delegate execution to the durable execution service
    - notify the user when autonomous execution reaches a terminal state

    Does not:
    - execute tools directly
    - bypass permission checks
    - modify workflow plans
    - retry failed workflows automatically

    The persistent workflow remains the source of truth.
    """

    def __init__(
        self,
        interval_seconds: int = 5,
        workflow_service: WorkflowService | None = None,
        execution_service: DurableWorkflowExecutionService | None = None,
        notification_service: NotificationService | None = None,
        batch_size: int = 20,
    ):
        if interval_seconds < 1:
            raise ValueError("interval_seconds must be at least 1")

        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")

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
        self.batch_size = batch_size
        self._running = False

    async def process_due_workflows(self) -> None:
        workflows = self.workflow_service.list_due_autonomous_workflows(
            limit=self.batch_size
        )

        for workflow in workflows:
            workflow_id = workflow["id"]
            user_id = workflow["user_id"]

            try:
                result = self.execution_service.execute(
                    user_id=user_id,
                    workflow_id=workflow_id,
                )

                self._notify_terminal_result(
                    workflow=workflow,
                    result=result,
                )

            except Exception:
                logger.exception(
                    "Autonomous workflow %s failed outside normal execution handling.",
                    workflow_id,
                )

    def _notify_terminal_result(
        self,
        *,
        workflow: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        status = result.get("status")

        if status not in {
            "completed",
            "failed",
            "partial",
            "blocked",
        }:
            return

        workflow_id = result.get("workflow_id") or workflow.get("id")

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
            body = f"Autonomous workflow #{workflow_id} failed."

        else:
            title = "NOVA background task was blocked"
            body = f"Autonomous workflow #{workflow_id} was blocked."

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
                "Could not notify user about autonomous workflow %s.",
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
                await asyncio.sleep(self.interval_seconds)

        finally:
            self._running = False

            logger.info(
                "NOVA autonomous workflow scheduler stopped."
            )

    def stop(self) -> None:
        self._running = False