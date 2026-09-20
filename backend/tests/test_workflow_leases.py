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


def build_runtime(
    *,
    lease_seconds=300,
):
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
            db_engine=db_engine,
            workflow_lease_seconds=lease_seconds,
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
                "task": "Lease test",
            },
            "depends_on": [],
        }
    ]


class FakeExecutionService:
    def __init__(
        self,
        result=None,
    ):
        self.calls = []

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


def autonomous_workflow(
    service,
):
    return service.create_workflow(
        user_id="user-001",
        conversation_id=None,
        plan={
            "execution_mode": "autonomous"
        },
        steps=workflow_steps(),
        execution_mode="autonomous",
        scheduled_at=None,
    )


def test_claim_workflow_creates_worker_lease():
    db_engine, service = build_runtime()

    try:
        workflow = autonomous_workflow(
            service
        )

        now = datetime(
            2026,
            9,
            20,
            6,
            30,
            tzinfo=timezone.utc,
        )

        claimed = service.claim_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
            expected_current_status="pending",
            now=now,
        )

        assert claimed is not None
        assert claimed["status"] == "running"

        assert claimed["claim_token"]
        assert len(
            claimed["claim_token"]
        ) >= 32

        assert (
            claimed["lease_until"]
            == datetime(
                2026,
                9,
                20,
                6,
                35,
            )
        )

        assert (
            claimed["heartbeat_at"]
            == datetime(
                2026,
                9,
                20,
                6,
                30,
            )
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_workflow_heartbeat_renews_only_with_current_lease_token():
    db_engine, service = build_runtime()

    try:
        workflow = autonomous_workflow(
            service
        )

        claim_time = datetime(
            2026,
            9,
            20,
            6,
            30,
            tzinfo=timezone.utc,
        )

        claimed = service.claim_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
            expected_current_status="pending",
            now=claim_time,
        )

        assert claimed is not None

        token = claimed["claim_token"]

        renewed = service.heartbeat_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
            claim_token=token,
            now=(
                claim_time
                + timedelta(
                    minutes=2
                )
            ),
        )

        assert renewed is not None
        assert renewed["status"] == "running"

        assert (
            renewed["heartbeat_at"]
            == datetime(
                2026,
                9,
                20,
                6,
                32,
            )
        )

        assert (
            renewed["lease_until"]
            == datetime(
                2026,
                9,
                20,
                6,
                37,
            )
        )

        wrong_token = service.heartbeat_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
            claim_token="wrong-token",
            now=(
                claim_time
                + timedelta(
                    minutes=2
                )
            ),
        )

        assert wrong_token is None

    finally:
        teardown_runtime(
            db_engine
        )


def test_workflow_heartbeat_cannot_renew_expired_lease():
    db_engine, service = build_runtime()

    try:
        workflow = autonomous_workflow(
            service
        )

        claim_time = datetime(
            2026,
            9,
            20,
            6,
            30,
            tzinfo=timezone.utc,
        )

        claimed = service.claim_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
            expected_current_status="pending",
            now=claim_time,
        )

        assert claimed is not None

        expired = service.heartbeat_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
            claim_token=claimed[
                "claim_token"
            ],
            now=(
                claim_time
                + timedelta(
                    minutes=6
                )
            ),
        )

        assert expired is None

    finally:
        teardown_runtime(
            db_engine
        )


def test_stale_workflow_recovery_returns_it_to_pending_and_resets_running_steps():
    db_engine, service = build_runtime()

    try:
        workflow = autonomous_workflow(
            service
        )

        claim_time = datetime(
            2026,
            9,
            20,
            6,
            30,
            tzinfo=timezone.utc,
        )

        claimed = service.claim_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
            expected_current_status="pending",
            now=claim_time,
        )

        assert claimed is not None

        claimed_step = service.claim_step(
            user_id="user-001",
            workflow_id=workflow["id"],
            step_id="step-1",
            workflow_claim_token=(
                claimed["claim_token"]
            ),
            now=claim_time,
        )

        assert claimed_step is not None
        assert claimed_step["status"] == "running"

        recovered = service.recover_stale_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
            now=(
                claim_time
                + timedelta(
                    minutes=6
                )
            ),
        )

        assert recovered is not None
        assert recovered["status"] == "pending"

        assert (
            recovered["claim_token"]
            is None
        )

        assert (
            recovered["lease_until"]
            is None
        )

        assert (
            recovered["heartbeat_at"]
            is None
        )

        current_step = recovered[
            "steps"
        ][0]

        assert (
            current_step["status"]
            == "pending"
        )

        assert recovered["error"]
        assert (
            "stale"
            in recovered["error"].lower()
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_stale_worker_is_fenced_after_workflow_recovery():
    db_engine, service = build_runtime()

    try:
        workflow = autonomous_workflow(
            service
        )

        claim_time = datetime(
            2026,
            9,
            20,
            6,
            30,
            tzinfo=timezone.utc,
        )

        claimed = service.claim_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
            expected_current_status="pending",
            now=claim_time,
        )

        assert claimed is not None

        stale_token = claimed[
            "claim_token"
        ]

        recovered = service.recover_stale_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
            now=(
                claim_time
                + timedelta(
                    minutes=6
                )
            ),
        )

        assert recovered is not None
        assert recovered["status"] == "pending"

        heartbeat = service.heartbeat_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
            claim_token=stale_token,
            now=(
                claim_time
                + timedelta(
                    minutes=7
                )
            ),
        )

        assert heartbeat is None

        stale_step_claim = service.claim_step(
            user_id="user-001",
            workflow_id=workflow["id"],
            step_id="step-1",
            workflow_claim_token=stale_token,
            now=(
                claim_time
                + timedelta(
                    minutes=7
                )
            ),
        )

        assert stale_step_claim is None

    finally:
        teardown_runtime(
            db_engine
        )


def test_active_workflow_is_not_recovered_before_lease_expiry():
    db_engine, service = build_runtime()

    try:
        workflow = autonomous_workflow(
            service
        )

        claim_time = datetime(
            2026,
            9,
            20,
            6,
            30,
            tzinfo=timezone.utc,
        )

        claimed = service.claim_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
            expected_current_status="pending",
            now=claim_time,
        )

        assert claimed is not None

        recovered = service.recover_stale_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
            now=(
                claim_time
                + timedelta(
                    minutes=2
                )
            ),
        )

        assert recovered is None

        current = service.get_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert current is not None
        assert current["status"] == "running"

    finally:
        teardown_runtime(
            db_engine
        )


@pytest.mark.asyncio
async def test_scheduler_recovers_stale_autonomous_workflow_before_processing_due_work(
    monkeypatch,
):
    db_engine, service = build_runtime()

    try:
        workflow = autonomous_workflow(
            service
        )

        claim_time = (
            datetime.now(
                timezone.utc
            )
            - timedelta(
                minutes=6
            )
        )

        claimed = service.claim_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
            expected_current_status="pending",
            now=claim_time,
        )

        assert claimed is not None
        assert claimed["status"] == "running"

        recovery_calls = []

        original_recover = (
            service.recover_stale_autonomous_workflows
        )

        def tracked_recovery(
            *,
            limit=50,
            now=None,
        ):
            recovered = original_recover(
                limit=limit,
                now=now,
            )

            recovery_calls.append(
                list(recovered)
            )

            return recovered

        monkeypatch.setattr(
            service,
            "recover_stale_autonomous_workflows",
            tracked_recovery,
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

        activity_event_service = (
            FakeActivityEventService()
        )

        scheduler = (
            AutonomousWorkflowScheduler(
                workflow_service=service,
                execution_service=execution_service,
                notification_service=(
                    notification_service
                ),
                activity_event_service=(
                    activity_event_service
                ),
            )
        )

        await scheduler.process_due_workflows()

        assert len(
            recovery_calls
        ) == 1

        assert len(
            recovery_calls[0]
        ) == 1

        assert (
            recovery_calls[0][0]["id"]
            == workflow["id"]
        )

        assert (
            recovery_calls[0][0]["status"]
            == "pending"
        )

        assert execution_service.calls == [
            {
                "user_id": "user-001",
                "workflow_id": workflow["id"],
            }
        ]

        assert len(
            notification_service.notifications
        ) == 1

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