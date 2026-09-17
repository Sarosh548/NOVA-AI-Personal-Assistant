from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from database.connection import engine as default_engine
from models.workflow import Workflow
from models.workflow_step import WorkflowStep


class WorkflowService:
    """
    Persistent workflow lifecycle service.

    Responsibilities:
    - create durable workflows
    - persist exact workflow step definitions
    - schedule autonomous workflows
    - find due autonomous workflows
    - manage workflow state transitions
    - atomically claim workflows
    - atomically claim individual steps
    - persist execution attempts/results
    - support resume/retry
    - rebuild durable workflow results

    This service does not execute tools.
    """

    CREATION_STATUSES = {
        "pending",
        "awaiting_confirmation",
    }

    TERMINAL_WORKFLOW_STATUSES = {
        "completed",
        "failed",
        "partial",
        "blocked",
        "cancelled",
    }

    WORKFLOW_TRANSITIONS = {
        "pending": {
            "awaiting_confirmation",
            "running",
            "cancelled",
            "failed",
            "blocked",
        },
        "awaiting_confirmation": {
            "running",
            "cancelled",
            "failed",
        },
        "running": {
            "completed",
            "partial",
            "failed",
            "blocked",
            "cancelled",
        },
        "partial": {
            "running",
            "cancelled",
        },
        "failed": {
            "running",
            "cancelled",
        },
        "blocked": {
            "running",
            "cancelled",
        },
        "completed": set(),
        "cancelled": set(),
    }

    def __init__(
        self,
        db_engine: Any | None = None,
    ):
        self.engine = (
            db_engine
            if db_engine is not None
            else default_engine
        )

    @staticmethod
    def _utc_now_naive() -> datetime:
        return datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    @staticmethod
    def _normalize_datetime(
        value: datetime | None,
    ) -> datetime | None:
        """
        Normalize datetime input to naive UTC.

        Naive values are treated as UTC because internal workflow
        timestamps are stored as naive UTC.
        """

        if value is None:
            return None

        if value.tzinfo is None:
            return value

        return value.astimezone(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    @classmethod
    def _json_safe(
        cls,
        value: Any,
    ) -> Any:
        """
        Convert common Python/SQLAlchemy values into JSON-safe
        structures.
        """

        if value is None:
            return None

        if isinstance(
            value,
            datetime,
        ):
            return value.isoformat()

        if isinstance(
            value,
            dict,
        ):
            return {
                str(key): cls._json_safe(item)
                for key, item in value.items()
            }

        if isinstance(
            value,
            (list, tuple),
        ):
            return [
                cls._json_safe(item)
                for item in value
            ]

        if isinstance(
            value,
            (str, int, float, bool),
        ):
            return value

        return str(value)

    def create_workflow(
        self,
        *,
        user_id: str,
        conversation_id: int | None,
        plan: dict[str, Any],
        steps: list[dict[str, Any]],
        execution_mode: str = "workflow",
        status: str = "pending",
        scheduled_at: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a durable workflow and its immutable execution
        step definitions.

        scheduled_at:
            Optional UTC datetime at which the workflow becomes
            eligible for autonomous background execution.

            A None scheduled_at means the workflow is eligible
            immediately, provided execution_mode is autonomous.
        """

        if not str(user_id).strip():
            raise ValueError(
                "Workflow user_id is missing."
            )

        if not isinstance(
            plan,
            dict,
        ):
            raise ValueError(
                "Workflow plan must be a dictionary."
            )

        if not isinstance(
            steps,
            list,
        ):
            raise ValueError(
                "Workflow steps must be a list."
            )

        if status not in self.CREATION_STATUSES:
            raise ValueError(
                "Invalid initial workflow status."
            )

        normalized_execution_mode = (
            str(execution_mode)
            .strip()
            .lower()
        )

        if not normalized_execution_mode:
            raise ValueError(
                "Workflow execution mode is missing."
            )

        normalized_scheduled_at = (
            self._normalize_datetime(
                scheduled_at
            )
        )

        normalized_idempotency_key = None

        if idempotency_key is not None:
            normalized_idempotency_key = str(
                idempotency_key
            ).strip()

            if not normalized_idempotency_key:
                normalized_idempotency_key = None

        normalized_steps = [
            self._normalize_step(
                step,
                position=index,
            )
            for index, step in enumerate(steps)
        ]

        self._validate_steps(
            normalized_steps
        )

        with Session(self.engine) as session:
            if normalized_idempotency_key is not None:
                existing = session.scalar(
                    select(Workflow).where(
                        Workflow.user_id == user_id,
                        Workflow.idempotency_key
                        == normalized_idempotency_key,
                    )
                )

                if existing is not None:
                    return self._workflow_to_dict(
                        session=session,
                        workflow=existing,
                    )

            now = self._utc_now_naive()

            workflow = Workflow(
                user_id=user_id,
                conversation_id=conversation_id,
                status=status,
                execution_mode=normalized_execution_mode,
                scheduled_at=normalized_scheduled_at,
                plan=self._json_safe(
                    plan
                ),
                result=None,
                error=None,
                idempotency_key=(
                    normalized_idempotency_key
                ),
                created_at=now,
                updated_at=now,
                started_at=None,
                completed_at=None,
            )

            session.add(
                workflow
            )

            session.flush()

            for step in normalized_steps:
                session.add(
                    WorkflowStep(
                        workflow_id=workflow.id,
                        step_id=step["step_id"],
                        position=step["position"],
                        tool=step["tool"],
                        action=step["action"],
                        data=self._json_safe(
                            step["data"]
                        ),
                        depends_on=self._json_safe(
                            step["depends_on"]
                        ),
                        status="pending",
                        result=None,
                        error=None,
                        attempts=0,
                        created_at=now,
                        updated_at=now,
                        started_at=None,
                        completed_at=None,
                    )
                )

            session.commit()
            session.refresh(
                workflow
            )

            return self._workflow_to_dict(
                session=session,
                workflow=workflow,
            )

    def get_workflow(
        self,
        *,
        user_id: str,
        workflow_id: int,
    ) -> dict[str, Any] | None:
        """
        Return a user's workflow with its persisted steps.
        """

        with Session(self.engine) as session:
            workflow = session.scalar(
                select(Workflow).where(
                    Workflow.id == workflow_id,
                    Workflow.user_id == user_id,
                )
            )

            if workflow is None:
                return None

            return self._workflow_to_dict(
                session=session,
                workflow=workflow,
            )

    def list_workflows(
        self,
        *,
        user_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Return recent workflows for a user.
        """

        normalized_limit = max(
            1,
            min(
                int(limit),
                200,
            ),
        )

        with Session(self.engine) as session:
            workflows = session.scalars(
                select(Workflow)
                .where(
                    Workflow.user_id == user_id
                )
                .order_by(
                    Workflow.created_at.desc(),
                    Workflow.id.desc(),
                )
                .limit(normalized_limit)
            ).all()

            return [
                self._workflow_to_dict(
                    session=session,
                    workflow=workflow,
                )
                for workflow in workflows
            ]

    def list_due_autonomous_workflows(
        self,
        *,
        limit: int = 50,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return autonomous workflows that are eligible for
        background execution.

        Only pending workflows are selected.

        This is intentionally separate from normal user-
        initiated workflow execution so an interactive workflow
        can never accidentally become background work.
        """

        normalized_now = (
            self._normalize_datetime(
                now
            )
            if now is not None
            else self._utc_now_naive()
        )

        normalized_limit = max(
            1,
            min(
                int(limit),
                200,
            ),
        )

        with Session(self.engine) as session:
            statement = (
                select(Workflow)
                .where(
                    Workflow.execution_mode
                    == "autonomous",
                    Workflow.status
                    == "pending",
                )
                .where(
                    (
                        Workflow.scheduled_at.is_(None)
                    )
                    | (
                        Workflow.scheduled_at
                        <= normalized_now
                    )
                )
                .order_by(
                    Workflow.scheduled_at.asc().nullsfirst(),
                    Workflow.created_at.asc(),
                    Workflow.id.asc(),
                )
                .limit(normalized_limit)
            )

            workflows = session.scalars(
                statement
            ).all()

            return [
                self._workflow_to_dict(
                    session=session,
                    workflow=workflow,
                )
                for workflow in workflows
            ]

    def set_awaiting_confirmation(
        self,
        *,
        user_id: str,
        workflow_id: int,
    ) -> dict[str, Any] | None:
        """
        Move a newly created workflow into the confirmation
        waiting state.
        """

        return self._transition(
            user_id=user_id,
            workflow_id=workflow_id,
            new_status="awaiting_confirmation",
            allowed_current_statuses={
                "pending",
            },
        )

    def claim_workflow(
        self,
        *,
        user_id: str,
        workflow_id: int,
    ) -> dict[str, Any] | None:
        """
        Atomically claim a workflow for execution.

        Only resumable states may be claimed:

            pending
            partial
            failed
            blocked

        An already-running workflow is not claimed again.
        """

        now = self._utc_now_naive()

        with Session(self.engine) as session:
            statement = (
                update(Workflow)
                .where(
                    Workflow.id == workflow_id,
                    Workflow.user_id == user_id,
                    Workflow.status.in_(
                        [
                            "pending",
                            "partial",
                            "failed",
                            "blocked",
                        ]
                    ),
                )
                .values(
                    status="running",
                    updated_at=now,
                    started_at=now,
                    completed_at=None,
                    error=None,
                )
            )

            result = session.execute(
                statement
            )

            if result.rowcount != 1:
                return None

            session.commit()

            workflow = session.scalar(
                select(Workflow).where(
                    Workflow.id == workflow_id,
                    Workflow.user_id == user_id,
                )
            )

            if workflow is None:
                return None

            return self._workflow_to_dict(
                session=session,
                workflow=workflow,
            )

    def cancel_workflow(
        self,
        *,
        user_id: str,
        workflow_id: int,
    ) -> dict[str, Any] | None:
        """
        Cancel a workflow that is not already terminal.
        """

        return self._transition(
            user_id=user_id,
            workflow_id=workflow_id,
            new_status="cancelled",
            allowed_current_statuses={
                "pending",
                "awaiting_confirmation",
                "running",
                "partial",
                "failed",
                "blocked",
            },
            completed_at=True,
        )

    def claim_step(
        self,
        *,
        user_id: str,
        workflow_id: int,
        step_id: str,
    ) -> dict[str, Any] | None:
        """
        Atomically claim exactly one workflow step.
        """

        now = self._utc_now_naive()

        with Session(self.engine) as session:
            workflow_exists = session.scalar(
                select(Workflow.id).where(
                    Workflow.id == workflow_id,
                    Workflow.user_id == user_id,
                    Workflow.status == "running",
                )
            )

            if workflow_exists is None:
                return None

            statement = (
                update(WorkflowStep)
                .where(
                    WorkflowStep.workflow_id
                    == workflow_id,
                    WorkflowStep.step_id
                    == step_id,
                    WorkflowStep.status.in_(
                        [
                            "pending",
                            "failed",
                            "blocked",
                            "skipped",
                        ]
                    ),
                )
                .values(
                    status="running",
                    attempts=WorkflowStep.attempts + 1,
                    updated_at=now,
                    started_at=now,
                    completed_at=None,
                    error=None,
                )
            )

            result = session.execute(
                statement
            )

            if result.rowcount != 1:
                return None

            session.commit()

            step = session.scalar(
                select(WorkflowStep).where(
                    WorkflowStep.workflow_id
                    == workflow_id,
                    WorkflowStep.step_id
                    == step_id,
                )
            )

            if step is None:
                return None

            return self._step_to_dict(
                step
            )

    def finish_step(
        self,
        *,
        user_id: str,
        workflow_id: int,
        step_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Persist the final result for a claimed step.

        Only the running state may be finalized.
        """

        if status not in {
            "completed",
            "failed",
            "skipped",
            "blocked",
        }:
            raise ValueError(
                "Invalid workflow step final status."
            )

        now = self._utc_now_naive()

        with Session(self.engine) as session:
            workflow = session.scalar(
                select(Workflow).where(
                    Workflow.id == workflow_id,
                    Workflow.user_id == user_id,
                )
            )

            if workflow is None:
                return None

            statement = (
                update(WorkflowStep)
                .where(
                    WorkflowStep.workflow_id
                    == workflow_id,
                    WorkflowStep.step_id
                    == step_id,
                    WorkflowStep.status
                    == "running",
                )
                .values(
                    status=status,
                    result=self._json_safe(
                        result
                    )
                    if result is not None
                    else None,
                    error=(
                        str(error)
                        if error is not None
                        else None
                    ),
                    updated_at=now,
                    completed_at=now,
                )
            )

            update_result = session.execute(
                statement
            )

            if update_result.rowcount != 1:
                return None

            session.commit()

            step = session.scalar(
                select(WorkflowStep).where(
                    WorkflowStep.workflow_id
                    == workflow_id,
                    WorkflowStep.step_id
                    == step_id,
                )
            )

            if step is None:
                return None

            return self._step_to_dict(
                step
            )

    def recalculate_workflow(
        self,
        *,
        user_id: str,
        workflow_id: int,
    ) -> dict[str, Any] | None:
        """
        Recalculate workflow status from persisted step state.
        """

        with Session(self.engine) as session:
            workflow = session.scalar(
                select(Workflow).where(
                    Workflow.id == workflow_id,
                    Workflow.user_id == user_id,
                )
            )

            if workflow is None:
                return None

            steps = session.scalars(
                select(WorkflowStep)
                .where(
                    WorkflowStep.workflow_id
                    == workflow_id
                )
                .order_by(
                    WorkflowStep.position.asc(),
                    WorkflowStep.id.asc(),
                )
            ).all()

            if workflow.status == "cancelled":
                return self._workflow_to_dict(
                    session=session,
                    workflow=workflow,
                )

            statuses = [
                step.status
                for step in steps
            ]

            now = self._utc_now_naive()

            if not steps:
                new_status = "completed"

            elif all(
                status == "completed"
                for status in statuses
            ):
                new_status = "completed"

            elif any(
                status in {
                    "pending",
                    "running",
                }
                for status in statuses
            ):
                new_status = "running"

            elif any(
                status == "completed"
                for status in statuses
            ) and any(
                status in {
                    "failed",
                    "skipped",
                    "blocked",
                }
                for status in statuses
            ):
                new_status = "partial"

            elif any(
                status == "failed"
                for status in statuses
            ):
                new_status = "failed"

            else:
                new_status = "blocked"

            result_payload = {
                "success": (
                    new_status == "completed"
                ),
                "status": new_status,
                "steps": [
                    self._json_safe(
                        self._step_to_dict(
                            step
                        )
                    )
                    for step in steps
                ],
                "error": (
                    "One or more workflow steps "
                    "did not complete successfully."
                    if new_status
                    in {
                        "failed",
                        "partial",
                        "blocked",
                    }
                    else None
                ),
            }

            workflow.status = new_status
            workflow.result = self._json_safe(
                result_payload
            )
            workflow.error = result_payload[
                "error"
            ]
            workflow.updated_at = now

            if (
                new_status
                in self.TERMINAL_WORKFLOW_STATUSES
            ):
                workflow.completed_at = now

            session.commit()
            session.refresh(
                workflow
            )

            return self._workflow_to_dict(
                session=session,
                workflow=workflow,
            )

    def _transition(
        self,
        *,
        user_id: str,
        workflow_id: int,
        new_status: str,
        allowed_current_statuses: set[str],
        completed_at: bool = False,
    ) -> dict[str, Any] | None:
        """
        Apply a guarded workflow state transition.
        """

        if new_status not in set(
            self.WORKFLOW_TRANSITIONS
        ):
            raise ValueError(
                "Invalid workflow status."
            )

        now = self._utc_now_naive()

        with Session(self.engine) as session:
            workflow = session.scalar(
                select(Workflow).where(
                    Workflow.id == workflow_id,
                    Workflow.user_id == user_id,
                )
            )

            if workflow is None:
                return None

            current_status = workflow.status

            if current_status not in (
                allowed_current_statuses
            ):
                return None

            allowed_transitions = (
                self.WORKFLOW_TRANSITIONS.get(
                    current_status,
                    set(),
                )
            )

            if new_status not in allowed_transitions:
                return None

            workflow.status = new_status
            workflow.updated_at = now

            if new_status == "running":
                workflow.started_at = now
                workflow.completed_at = None

            elif completed_at:
                workflow.completed_at = now

            session.commit()
            session.refresh(
                workflow
            )

            return self._workflow_to_dict(
                session=session,
                workflow=workflow,
            )

    def _normalize_step(
        self,
        step: dict[str, Any],
        *,
        position: int,
    ) -> dict[str, Any]:
        if not isinstance(
            step,
            dict,
        ):
            raise ValueError(
                "Every workflow step must be a dictionary."
            )

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

        data = step.get(
            "data",
            {},
        )

        depends_on = step.get(
            "depends_on",
            [],
        )

        if not step_id:
            raise ValueError(
                "Workflow step ID is missing."
            )

        if not tool:
            raise ValueError(
                f"Workflow step '{step_id}' has no tool."
            )

        if not action:
            raise ValueError(
                f"Workflow step '{step_id}' has no action."
            )

        if not isinstance(
            data,
            dict,
        ):
            raise ValueError(
                f"Workflow step '{step_id}' data "
                "must be a dictionary."
            )

        if depends_on is None:
            depends_on = []

        if not isinstance(
            depends_on,
            (list, tuple),
        ):
            raise ValueError(
                f"Workflow step '{step_id}' dependencies "
                "must be a list."
            )

        return {
            "step_id": step_id,
            "position": position,
            "tool": tool,
            "action": action,
            "data": dict(data),
            "depends_on": [
                str(item).strip()
                for item in depends_on
            ],
        }

    def _validate_steps(
        self,
        steps: list[dict[str, Any]],
    ) -> None:
        step_ids = {
            step["step_id"]
            for step in steps
        }

        if len(step_ids) != len(steps):
            raise ValueError(
                "Workflow step IDs must be unique."
            )

        for step in steps:
            dependencies = set(
                step["depends_on"]
            )

            if (
                step["step_id"]
                in dependencies
            ):
                raise ValueError(
                    f"Workflow step '{step['step_id']}' "
                    "cannot depend on itself."
                )

            unknown = (
                dependencies - step_ids
            )

            if unknown:
                raise ValueError(
                    f"Workflow step '{step['step_id']}' "
                    "depends on unknown step(s): "
                    f"{', '.join(sorted(unknown))}."
                )

        graph = {
            step["step_id"]: set(
                step["depends_on"]
            )
            for step in steps
        }

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(
            node: str,
        ) -> None:
            if node in visiting:
                raise ValueError(
                    "Workflow dependencies contain a cycle."
                )

            if node in visited:
                return

            visiting.add(node)

            for dependency in graph[node]:
                visit(
                    dependency
                )

            visiting.remove(node)
            visited.add(node)

        for step_id in graph:
            visit(step_id)

    def _workflow_to_dict(
        self,
        *,
        session: Session,
        workflow: Workflow,
    ) -> dict[str, Any]:
        steps = session.scalars(
            select(WorkflowStep)
            .where(
                WorkflowStep.workflow_id
                == workflow.id
            )
            .order_by(
                WorkflowStep.position.asc(),
                WorkflowStep.id.asc(),
            )
        ).all()

        return {
            "id": workflow.id,
            "user_id": workflow.user_id,
            "conversation_id": (
                workflow.conversation_id
            ),
            "status": workflow.status,
            "execution_mode": (
                workflow.execution_mode
            ),
            "scheduled_at": workflow.scheduled_at,
            "plan": workflow.plan,
            "result": workflow.result,
            "error": workflow.error,
            "idempotency_key": (
                workflow.idempotency_key
            ),
            "created_at": workflow.created_at,
            "updated_at": workflow.updated_at,
            "started_at": workflow.started_at,
            "completed_at": workflow.completed_at,
            "steps": [
                self._step_to_dict(
                    step
                )
                for step in steps
            ],
        }

    @staticmethod
    def _step_to_dict(
        step: WorkflowStep,
    ) -> dict[str, Any]:
        return {
            "id": step.id,
            "workflow_id": step.workflow_id,
            "step_id": step.step_id,
            "position": step.position,
            "tool": step.tool,
            "action": step.action,
            "data": step.data,
            "depends_on": step.depends_on,
            "status": step.status,
            "result": step.result,
            "error": step.error,
            "attempts": step.attempts,
            "created_at": step.created_at,
            "updated_at": step.updated_at,
            "started_at": step.started_at,
            "completed_at": step.completed_at,
        }