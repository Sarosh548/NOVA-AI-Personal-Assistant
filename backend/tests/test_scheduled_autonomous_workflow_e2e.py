from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.activity_event import ActivityEvent
from models.workflow import Workflow
from models.workflow_step import WorkflowStep
from services.activity_event_service import (
    ActivityEventService,
)
from services.autonomous_workflow_scheduler import (
    AutonomousWorkflowScheduler,
)
from services.autonomous_workflow_service import (
    AutonomousWorkflowService,
)
from services.durable_workflow_execution_service import (
    DurableWorkflowExecutionService,
)
from services.workflow_execution_safety_service import (
    WorkflowExecutionSafetyDecision,
)
from services.workflow_service import WorkflowService


class FakeToolRouter:
    def __init__(self):
        self.calls = []

    def execute(
        self,
        intent,
        user_id,
        data,
    ):
        self.calls.append(
            {
                "intent": intent,
                "user_id": user_id,
                "data": data,
            }
        )

        return {
            "success": True,
            "tool": intent,
            "action": "create",
            "result": {
                "executed": True,
            },
            "error": None,
        }


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


class FakeExecutionSafetyService:
    def __init__(self):
        self.calls = []

    def check(
        self,
        *,
        user_id,
        steps,
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "steps": steps,
            }
        )

        return WorkflowExecutionSafetyDecision(
            allowed=True,
            requires_confirmation=False,
            reason=(
                "The scheduled workflow is currently "
                "authorized for execution."
            ),
            risk_levels={
                step["step_id"]: "medium"
                for step in steps
            },
            risk_flags={
                step["step_id"]: ()
                for step in steps
            },
        )


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

    ActivityEvent.__table__.create(
        bind=db_engine
    )

    workflow_service = WorkflowService(
        db_engine=db_engine
    )

    activity_event_service = (
        ActivityEventService(
            db_engine=db_engine
        )
    )

    return (
        db_engine,
        workflow_service,
        activity_event_service,
    )


def teardown_runtime(
    db_engine,
):
    ActivityEvent.__table__.drop(
        bind=db_engine
    )

    WorkflowStep.__table__.drop(
        bind=db_engine
    )

    Workflow.__table__.drop(
        bind=db_engine
    )

    db_engine.dispose()


def scheduled_steps():
    return [
        {
            "step_id": "step-1",
            "tool": "task",
            "action": "create",
            "data": {
                "task": "Complete NOVA E2E test",
            },
            "depends_on": [],
        }
    ]


@pytest.mark.asyncio
async def test_scheduled_workflow_completes_end_to_end():
    (
        db_engine,
        workflow_service,
        activity_event_service,
    ) = build_runtime()

    try:
        autonomous_service = (
            AutonomousWorkflowService(
                db_engine=db_engine,
                workflow_service=workflow_service,
                activity_event_service=(
                    activity_event_service
                ),
            )
        )

        fixed_creation_now = datetime(
            2026,
            9,
            18,
            5,
            0,
            0,
            tzinfo=timezone.utc,
        )

        autonomous_service._utc_now = (
            lambda: fixed_creation_now
        )

        router = FakeToolRouter()

        safety_service = (
            FakeExecutionSafetyService()
        )

        executor = (
            DurableWorkflowExecutionService(
                workflow_service=workflow_service,
                tool_router=router,
                execution_safety_service=(
                    safety_service
                ),
            )
        )

        notification_service = (
            FakeNotificationService()
        )

        scheduler = (
            AutonomousWorkflowScheduler(
                interval_seconds=5,
                workflow_service=workflow_service,
                execution_service=executor,
                notification_service=notification_service,
                activity_event_service=(
                    activity_event_service
                ),
            )
        )

        scheduled_at = datetime(
            2026,
            9,
            18,
            5,
            5,
            0,
            tzinfo=timezone.utc,
        )

        workflow = (
            autonomous_service
            .create_scheduled_workflow(
                user_id="user-001",
                conversation_id=99,
                plan={
                    "requires_tool": True,
                    "execution_mode": "autonomous",
                    "scheduled_at": (
                        scheduled_at.isoformat()
                    ),
                },
                steps=scheduled_steps(),
                scheduled_at=scheduled_at,
                idempotency_key="e2e-scheduled-001",
            )
        )

        assert workflow["id"] is not None
        assert workflow["status"] == "pending"
        assert workflow["execution_mode"] == "autonomous"
        assert workflow["scheduled_at"] == datetime(
            2026,
            9,
            18,
            5,
            5,
            0,
        )

        assert router.calls == []

        scheduled_events = (
            activity_event_service.list_events(
                user_id="user-001",
                event_type="workflow_scheduled",
            )
        )

        assert len(
            scheduled_events
        ) == 1

        assert (
            scheduled_events[0][
                "workflow_id"
            ]
            == workflow["id"]
        )

        assert (
            scheduled_events[0][
                "status"
            ]
            == "pending"
        )

        await scheduler.process_due_workflows()

        assert len(
            safety_service.calls
        ) == 1

        assert (
            safety_service.calls[0][
                "user_id"
            ]
            == "user-001"
        )

        assert (
            safety_service.calls[0][
                "steps"
            ][0]["step_id"]
            == "step-1"
        )

        final_workflow = (
            workflow_service.get_workflow(
                user_id="user-001",
                workflow_id=workflow["id"],
            )
        )

        assert final_workflow is not None

        assert (
            final_workflow["status"]
            == "completed"
        )

        assert (
            final_workflow["execution_mode"]
            == "autonomous"
        )

        assert (
            final_workflow["scheduled_at"]
            == datetime(
                2026,
                9,
                18,
                5,
                5,
                0,
            )
        )

        assert (
            len(final_workflow["steps"])
            == 1
        )

        assert (
            final_workflow["steps"][0][
                "status"
            ]
            == "completed"
        )

        assert (
            final_workflow["steps"][0][
                "attempts"
            ]
            == 1
        )

        assert router.calls == [
            {
                "intent": "task",
                "user_id": "user-001",
                "data": {
                    "task": "Complete NOVA E2E test",
                },
            }
        ]

        completed_events = (
            activity_event_service.list_events(
                user_id="user-001",
                event_type="workflow_completed",
            )
        )

        assert len(
            completed_events
        ) == 1

        completed_event = (
            completed_events[0]
        )

        assert (
            completed_event["workflow_id"]
            == workflow["id"]
        )

        assert (
            completed_event["status"]
            == "success"
        )

        assert (
            completed_event["metadata"][
                "status"
            ]
            == "completed"
        )

        assert (
            len(
                notification_service.notifications
            )
            == 1
        )

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
            notification["metadata"][
                "workflow_id"
            ]
            == workflow["id"]
        )

        assert (
            notification["metadata"]["status"]
            == "completed"
        )

    finally:
        teardown_runtime(
            db_engine
        )