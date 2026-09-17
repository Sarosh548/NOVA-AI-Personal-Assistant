from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.workflow import Workflow
from models.workflow_step import WorkflowStep
from services.autonomous_workflow_scheduler import (
    AutonomousWorkflowScheduler,
)
from services.workflow_service import WorkflowService


def build_runtime():
    db_engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    Workflow.__table__.create(
        bind=db_engine
    )

    WorkflowStep.__table__.create(
        bind=db_engine
    )

    service = WorkflowService(
        db_engine=db_engine
    )

    return db_engine, service


def teardown_runtime(
    db_engine,
):
    WorkflowStep.__table__.drop(
        bind=db_engine
    )

    Workflow.__table__.drop(
        bind=db_engine
    )

    db_engine.dispose()


def autonomous_steps():
    return [
        {
            "step_id": "step-1",
            "tool": "task",
            "action": "create",
            "data": {
                "task": "Daily planning",
            },
            "depends_on": [],
        }
    ]


class FakeExecutionService:
    def __init__(
        self,
        result=None,
    ):
        self.result = (
            result
            if result is not None
            else {
                "success": True,
                "status": "completed",
                "workflow_id": 1,
                "steps": [],
                "error": None,
            }
        )
        self.calls = []

    def execute(
        self,
        *,
        user_id,
        workflow_id,
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "workflow_id": workflow_id,
            }
        )

        return dict(
            self.result
        )


class FakeNotificationService:
    def __init__(self):
        self.notifications = []

    def notify(
        self,
        **kwargs,
    ):
        self.notifications.append(
            kwargs
        )
        return True


@pytest.mark.asyncio
async def test_scheduler_executes_due_autonomous_workflow():
    db_engine, service = build_runtime()

    try:
        now = datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

        workflow = service.create_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={
                "execution_mode": "autonomous"
            },
            steps=autonomous_steps(),
            execution_mode="autonomous",
            scheduled_at=(
                now - timedelta(
                    seconds=5
                )
            ),
        )

        execution_service = (
            FakeExecutionService(
                result={
                    "success": True,
                    "status": "completed",
                    "workflow_id": workflow["id"],
                    "steps": [],
                    "error": None,
                }
            )
        )

        notification_service = (
            FakeNotificationService()
        )

        scheduler = (
            AutonomousWorkflowScheduler(
                interval_seconds=5,
                workflow_service=service,
                execution_service=execution_service,
                notification_service=notification_service,
            )
        )

        await scheduler.process_due_workflows()

        assert execution_service.calls == [
            {
                "user_id": "user-001",
                "workflow_id": workflow["id"],
            }
        ]

        assert len(
            notification_service.notifications
        ) == 1

        notification = (
            notification_service.notifications[0]
        )

        assert (
            notification["user_id"]
            == "user-001"
        )

        assert (
            notification["notification_type"]
            == "workflow"
        )

        assert (
            notification["metadata"]["workflow_id"]
            == workflow["id"]
        )

    finally:
        teardown_runtime(
            db_engine
        )


@pytest.mark.asyncio
async def test_scheduler_ignores_future_autonomous_workflow():
    db_engine, service = build_runtime()

    try:
        now = datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

        workflow = service.create_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={
                "execution_mode": "autonomous"
            },
            steps=autonomous_steps(),
            execution_mode="autonomous",
            scheduled_at=(
                now + timedelta(
                    minutes=10
                )
            ),
        )

        execution_service = (
            FakeExecutionService()
        )

        notification_service = (
            FakeNotificationService()
        )

        scheduler = (
            AutonomousWorkflowScheduler(
                workflow_service=service,
                execution_service=execution_service,
                notification_service=notification_service,
            )
        )

        await scheduler.process_due_workflows()

        assert execution_service.calls == []
        assert notification_service.notifications == []

        current = service.get_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert current is not None
        assert current["status"] == "pending"

    finally:
        teardown_runtime(
            db_engine
        )


@pytest.mark.asyncio
async def test_scheduler_does_not_pick_interactive_workflow():
    db_engine, service = build_runtime()

    try:
        now = datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

        workflow = service.create_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={
                "execution_mode": "workflow"
            },
            steps=autonomous_steps(),
            execution_mode="workflow",
            scheduled_at=(
                now - timedelta(
                    seconds=5
                )
            ),
        )

        execution_service = (
            FakeExecutionService()
        )

        notification_service = (
            FakeNotificationService()
        )

        scheduler = (
            AutonomousWorkflowScheduler(
                workflow_service=service,
                execution_service=execution_service,
                notification_service=notification_service,
            )
        )

        await scheduler.process_due_workflows()

        assert execution_service.calls == []
        assert notification_service.notifications == []

        current = service.get_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert current is not None
        assert current["status"] == "pending"

    finally:
        teardown_runtime(
            db_engine
        )


@pytest.mark.asyncio
async def test_scheduler_can_process_immediately_eligible_autonomous_workflow():
    db_engine, service = build_runtime()

    try:
        workflow = service.create_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={
                "execution_mode": "autonomous"
            },
            steps=autonomous_steps(),
            execution_mode="autonomous",
            scheduled_at=None,
        )

        execution_service = (
            FakeExecutionService(
                result={
                    "success": False,
                    "status": "failed",
                    "workflow_id": workflow["id"],
                    "steps": [],
                    "error": "Background execution failed.",
                }
            )
        )

        notification_service = (
            FakeNotificationService()
        )

        scheduler = (
            AutonomousWorkflowScheduler(
                workflow_service=service,
                execution_service=execution_service,
                notification_service=notification_service,
            )
        )

        await scheduler.process_due_workflows()

        assert len(
            execution_service.calls
        ) == 1

        assert len(
            notification_service.notifications
        ) == 1

        notification = (
            notification_service.notifications[0]
        )

        assert (
            notification["metadata"]["status"]
            == "failed"
        )

    finally:
        teardown_runtime(
            db_engine
        )


@pytest.mark.asyncio
async def test_scheduler_does_not_notify_non_terminal_execution():
    db_engine, service = build_runtime()

    try:
        workflow = service.create_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={
                "execution_mode": "autonomous"
            },
            steps=autonomous_steps(),
            execution_mode="autonomous",
            scheduled_at=None,
        )

        execution_service = (
            FakeExecutionService(
                result={
                    "success": False,
                    "status": "awaiting_confirmation",
                    "workflow_id": workflow["id"],
                    "steps": [],
                    "error": None,
                }
            )
        )

        notification_service = (
            FakeNotificationService()
        )

        scheduler = (
            AutonomousWorkflowScheduler(
                workflow_service=service,
                execution_service=execution_service,
                notification_service=notification_service,
            )
        )

        await scheduler.process_due_workflows()

        assert len(
            execution_service.calls
        ) == 1

        assert notification_service.notifications == []

    finally:
        teardown_runtime(
            db_engine
        )


@pytest.mark.asyncio
async def test_scheduler_continues_when_one_workflow_raises():
    db_engine, service = build_runtime()

    try:
        first = service.create_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={
                "execution_mode": "autonomous"
            },
            steps=autonomous_steps(),
            execution_mode="autonomous",
            scheduled_at=None,
        )

        second = service.create_workflow(
            user_id="user-002",
            conversation_id=None,
            plan={
                "execution_mode": "autonomous"
            },
            steps=autonomous_steps(),
            execution_mode="autonomous",
            scheduled_at=None,
        )

        class ResilientExecutionService:
            def __init__(self):
                self.calls = []

            def execute(
                self,
                *,
                user_id,
                workflow_id,
            ):
                self.calls.append(
                    workflow_id
                )

                if workflow_id == first["id"]:
                    raise RuntimeError(
                        "simulated failure"
                    )

                return {
                    "success": True,
                    "status": "completed",
                    "workflow_id": workflow_id,
                    "steps": [],
                    "error": None,
                }

        execution_service = (
            ResilientExecutionService()
        )

        notification_service = (
            FakeNotificationService()
        )

        scheduler = (
            AutonomousWorkflowScheduler(
                workflow_service=service,
                execution_service=execution_service,
                notification_service=notification_service,
            )
        )

        await scheduler.process_due_workflows()

        assert execution_service.calls == [
            first["id"],
            second["id"],
        ]

        assert len(
            notification_service.notifications
        ) == 1

        assert (
            notification_service.notifications[0]
            ["metadata"]["workflow_id"]
            == second["id"]
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_scheduler_rejects_invalid_interval():
    with pytest.raises(
        ValueError,
        match="interval_seconds must be at least 1",
    ):
        AutonomousWorkflowScheduler(
            interval_seconds=0
        )


def test_scheduler_rejects_invalid_batch_size():
    with pytest.raises(
        ValueError,
        match="batch_size must be at least 1",
    ):
        AutonomousWorkflowScheduler(
            batch_size=0
        )