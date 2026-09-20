from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.workflow import Workflow
from models.workflow_step import WorkflowStep
from services.autonomous_workflow_scheduler import (
    AutonomousWorkflowScheduler,
)
from services.durable_workflow_execution_service import (
    DurableWorkflowExecutionService,
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

    return (
        db_engine,
        WorkflowService(
            db_engine=db_engine
        ),
    )


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


def workflow_steps():
    return [
        {
            "step_id": "step-1",
            "tool": "task",
            "action": "create",
            "data": {
                "task": "Concurrency test",
            },
            "depends_on": [],
        }
    ]


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


class FakeSafetyService:
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

        return type(
            "Decision",
            (),
            {
                "allowed": True,
                "requires_confirmation": False,
                "reason": "allowed",
            },
        )()


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


class FakeActivityEventService:
    def __init__(self):
        self.events = []

    def record_event(
        self,
        **kwargs,
    ):
        self.events.append(
            kwargs
        )

        return kwargs


def test_claim_workflow_can_require_expected_status():
    db_engine, service = build_runtime()

    try:
        workflow = service.create_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={},
            steps=workflow_steps(),
        )

        first = service.claim_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
            expected_current_status="pending",
        )

        assert first is not None
        assert first["status"] == "running"

        second = service.claim_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
            expected_current_status="pending",
        )

        assert second is None

    finally:
        teardown_runtime(
            db_engine
        )


def test_autonomous_executor_does_not_retry_stale_pending_snapshot():
    db_engine, service = build_runtime()

    try:
        workflow = service.create_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={
                "execution_mode": "autonomous"
            },
            steps=workflow_steps(),
            execution_mode="autonomous",
        )

        competitor = WorkflowService(
            db_engine=db_engine
        )

        class RacingWorkflowService:
            def __init__(self):
                self.raced = False

            def get_workflow(
                self,
                *,
                user_id,
                workflow_id,
            ):
                return service.get_workflow(
                    user_id=user_id,
                    workflow_id=workflow_id,
                )

            def claim_workflow(
                self,
                *,
                user_id,
                workflow_id,
                expected_current_status=None,
            ):
                if not self.raced:
                    self.raced = True

                    claimed = competitor.claim_workflow(
                        user_id=user_id,
                        workflow_id=workflow_id,
                    )

                    assert claimed is not None

                    blocked = competitor.block_workflow(
                        user_id=user_id,
                        workflow_id=workflow_id,
                        reason=(
                            "Simulated competing worker "
                            "changed the workflow state."
                        ),
                    )

                    assert blocked is not None

                return service.claim_workflow(
                    user_id=user_id,
                    workflow_id=workflow_id,
                    expected_current_status=(
                        expected_current_status
                    ),
                )

            def __getattr__(
                self,
                name,
            ):
                return getattr(
                    service,
                    name,
                )

        racing_service = (
            RacingWorkflowService()
        )

        router = FakeToolRouter()
        safety_service = FakeSafetyService()

        executor = (
            DurableWorkflowExecutionService(
                workflow_service=racing_service,
                tool_router=router,
                execution_safety_service=(
                    safety_service
                ),
            )
        )

        result = executor.execute(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert result["status"] == "blocked"
        assert (
            result["terminal_effect_owner"]
            is False
        )

        assert safety_service.calls == []
        assert router.calls == []

    finally:
        teardown_runtime(
            db_engine
        )


def test_scheduler_emits_terminal_side_effects_only_for_owner():
    workflow = {
        "id": 9001,
        "user_id": "user-001",
        "conversation_id": None,
        "execution_mode": "autonomous",
        "scheduled_at": None,
    }

    class ReplayWorkflowService:
        def __init__(self):
            self.calls = 0

        def list_due_autonomous_workflows(
            self,
            *,
            limit,
        ):
            self.calls += 1

            return [
                dict(workflow)
            ]

    class SequenceExecutionService:
        def __init__(self):
            self.calls = 0

        def execute(
            self,
            *,
            user_id,
            workflow_id,
        ):
            self.calls += 1

            if self.calls == 1:
                return {
                    "success": True,
                    "status": "completed",
                    "workflow_id": workflow_id,
                    "steps": [],
                    "error": None,
                    "terminal_effect_owner": True,
                }

            return {
                "success": True,
                "status": "completed",
                "workflow_id": workflow_id,
                "steps": [],
                "error": None,
                "terminal_effect_owner": False,
            }

    workflow_service = (
        ReplayWorkflowService()
    )

    execution_service = (
        SequenceExecutionService()
    )

    notification_service = (
        FakeNotificationService()
    )

    activity_event_service = (
        FakeActivityEventService()
    )

    scheduler = (
        AutonomousWorkflowScheduler(
            workflow_service=workflow_service,
            execution_service=execution_service,
            notification_service=notification_service,
            activity_event_service=(
                activity_event_service
            ),
        )
    )

    import asyncio

    asyncio.run(
        scheduler.process_due_workflows()
    )

    asyncio.run(
        scheduler.process_due_workflows()
    )

    assert execution_service.calls == 2

    assert len(
        activity_event_service.events
    ) == 1

    assert len(
        notification_service.notifications
    ) == 1

def test_observer_of_failed_competing_workflow_is_not_owner():
    db_engine, service = build_runtime()

    try:
        workflow = service.create_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={
                "execution_mode": "autonomous"
            },
            steps=workflow_steps(),
            execution_mode="autonomous",
        )

        competitor = WorkflowService(
            db_engine=db_engine
        )

        class RacingWorkflowService:
            def __init__(self):
                self.raced = False

            def get_workflow(
                self,
                *,
                user_id,
                workflow_id,
            ):
                return service.get_workflow(
                    user_id=user_id,
                    workflow_id=workflow_id,
                )

            def claim_workflow(
                self,
                *,
                user_id,
                workflow_id,
                expected_current_status=None,
            ):
                if not self.raced:
                    self.raced = True

                    claimed = (
                        competitor.claim_workflow(
                            user_id=user_id,
                            workflow_id=workflow_id,
                        )
                    )

                    assert claimed is not None

                    failed_step = (
                        competitor.claim_step(
                            user_id=user_id,
                            workflow_id=workflow_id,
                            step_id="step-1",
                        )
                    )

                    assert failed_step is not None

                    finished = (
                        competitor.finish_step(
                            user_id=user_id,
                            workflow_id=workflow_id,
                            step_id="step-1",
                            status="failed",
                            result={},
                            error="Simulated worker failure.",
                        )
                    )

                    assert finished is not None

                    failed_workflow = (
                        competitor.recalculate_workflow(
                            user_id=user_id,
                            workflow_id=workflow_id,
                        )
                    )

                    assert failed_workflow is not None
                    assert (
                        failed_workflow["status"]
                        == "failed"
                    )

                return service.claim_workflow(
                    user_id=user_id,
                    workflow_id=workflow_id,
                    expected_current_status=(
                        expected_current_status
                    ),
                )

            def __getattr__(
                self,
                name,
            ):
                return getattr(
                    service,
                    name,
                )

        racing_service = (
            RacingWorkflowService()
        )

        router = FakeToolRouter()
        safety_service = FakeSafetyService()

        executor = (
            DurableWorkflowExecutionService(
                workflow_service=racing_service,
                tool_router=router,
                execution_safety_service=(
                    safety_service
                ),
            )
        )

        result = executor.execute(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert result["status"] == "failed"
        assert (
            result["terminal_effect_owner"]
            is False
        )

        assert safety_service.calls == []
        assert router.calls == []

    finally:
        teardown_runtime(db_engine)
