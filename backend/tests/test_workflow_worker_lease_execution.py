from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.workflow import Workflow
from models.workflow_step import WorkflowStep
from services.durable_workflow_execution_service import (
    DurableWorkflowExecutionService,
)
from services.workflow_service import WorkflowService


class FakeToolRouter:
    def __init__(self):
        self.calls = []

    def execute(
        self,
        *,
        intent,
        user_id,
        data,
    ):
        self.calls.append(
            {
                "intent": intent,
                "user_id": user_id,
                "data": dict(data),
            }
        )

        return {
            "success": True,
            "result": {
                "executed": True,
            },
            "error": None,
        }


def build_runtime(
    *,
    workflow_lease_seconds=300,
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

    service = WorkflowService(
        db_engine=db_engine,
        workflow_lease_seconds=(
            workflow_lease_seconds
        ),
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


def create_workflow(
    service,
    *,
    steps=None,
):
    if steps is None:
        steps = [
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "create",
                "data": {
                    "task": "Lease executor test",
                },
                "depends_on": [],
            }
        ]

    return service.create_workflow(
        user_id="user-001",
        conversation_id=None,
        plan={
            "execution_mode": "workflow",
        },
        steps=steps,
        execution_mode="workflow",
    )


def test_executor_propagates_workflow_claim_token_and_heartbeats(
    monkeypatch,
):
    db_engine, service = build_runtime()

    try:
        workflow = create_workflow(
            service
        )

        tool_router = FakeToolRouter()

        execution_service = (
            DurableWorkflowExecutionService(
                workflow_service=service,
                tool_router=tool_router,
            )
        )

        original_claim_workflow = (
            service.claim_workflow
        )

        original_heartbeat = (
            service.heartbeat_workflow
        )

        original_claim_step = (
            service.claim_step
        )

        original_finish_step = (
            service.finish_step
        )

        original_recalculate = (
            service.recalculate_workflow
        )

        claim_state = {
            "token": None,
        }

        heartbeat_calls = []
        claim_step_calls = []
        finish_step_calls = []
        recalculate_calls = []

        def tracked_claim_workflow(
            *,
            user_id,
            workflow_id,
            expected_current_status=None,
            now=None,
        ):
            result = original_claim_workflow(
                user_id=user_id,
                workflow_id=workflow_id,
                expected_current_status=(
                    expected_current_status
                ),
                now=now,
            )

            assert result is not None

            claim_state["token"] = (
                result["claim_token"]
            )

            return result

        def tracked_heartbeat(
            *,
            user_id,
            workflow_id,
            claim_token,
            now=None,
        ):
            heartbeat_calls.append(
                {
                    "user_id": user_id,
                    "workflow_id": workflow_id,
                    "claim_token": claim_token,
                }
            )

            return original_heartbeat(
                user_id=user_id,
                workflow_id=workflow_id,
                claim_token=claim_token,
                now=now,
            )

        def tracked_claim_step(
            *,
            user_id,
            workflow_id,
            step_id,
            workflow_claim_token=None,
            now=None,
        ):
            claim_step_calls.append(
                {
                    "step_id": step_id,
                    "workflow_claim_token": (
                        workflow_claim_token
                    ),
                }
            )

            return original_claim_step(
                user_id=user_id,
                workflow_id=workflow_id,
                step_id=step_id,
                workflow_claim_token=(
                    workflow_claim_token
                ),
                now=now,
            )

        def tracked_finish_step(
            *,
            user_id,
            workflow_id,
            step_id,
            status,
            result=None,
            error=None,
            workflow_claim_token=None,
            now=None,
        ):
            finish_step_calls.append(
                {
                    "step_id": step_id,
                    "workflow_claim_token": (
                        workflow_claim_token
                    ),
                }
            )

            return original_finish_step(
                user_id=user_id,
                workflow_id=workflow_id,
                step_id=step_id,
                status=status,
                result=result,
                error=error,
                workflow_claim_token=(
                    workflow_claim_token
                ),
                now=now,
            )

        def tracked_recalculate(
            *,
            user_id,
            workflow_id,
            workflow_claim_token=None,
            now=None,
        ):
            recalculate_calls.append(
                {
                    "workflow_claim_token": (
                        workflow_claim_token
                    ),
                }
            )

            return original_recalculate(
                user_id=user_id,
                workflow_id=workflow_id,
                workflow_claim_token=(
                    workflow_claim_token
                ),
                now=now,
            )

        monkeypatch.setattr(
            service,
            "claim_workflow",
            tracked_claim_workflow,
        )

        monkeypatch.setattr(
            service,
            "heartbeat_workflow",
            tracked_heartbeat,
        )

        monkeypatch.setattr(
            service,
            "claim_step",
            tracked_claim_step,
        )

        monkeypatch.setattr(
            service,
            "finish_step",
            tracked_finish_step,
        )

        monkeypatch.setattr(
            service,
            "recalculate_workflow",
            tracked_recalculate,
        )

        result = execution_service.execute(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert result["success"] is True
        assert result["status"] == "completed"

        assert claim_state["token"]

        assert (
            len(heartbeat_calls)
            >= 2
        )

        assert all(
            call["claim_token"]
            == claim_state["token"]
            for call in heartbeat_calls
        )

        assert (
            len(claim_step_calls)
            >= 1
        )

        assert all(
            call["workflow_claim_token"]
            == claim_state["token"]
            for call in claim_step_calls
        )

        assert (
            len(finish_step_calls)
            >= 1
        )

        assert all(
            call["workflow_claim_token"]
            == claim_state["token"]
            for call in finish_step_calls
        )

        assert (
            len(recalculate_calls)
            >= 1
        )

        assert all(
            call["workflow_claim_token"]
            == claim_state["token"]
            for call in recalculate_calls
        )

        assert len(
            tool_router.calls
        ) == 1

    finally:
        teardown_runtime(
            db_engine
        )



def test_executor_heartbeats_during_long_running_tool_execution():
    import time

    db_engine, service = build_runtime(
        workflow_lease_seconds=2,
    )

    try:
        workflow = create_workflow(
            service
        )

        class SlowToolRouter(FakeToolRouter):
            def execute(
                self,
                *,
                intent,
                user_id,
                data,
            ):
                self.calls.append(
                    {
                        "intent": intent,
                        "user_id": user_id,
                        "data": dict(data),
                    }
                )

                time.sleep(2.5)

                return {
                    "success": True,
                    "result": {
                        "executed": True,
                    },
                    "error": None,
                }

        tool_router = SlowToolRouter()

        execution_service = (
            DurableWorkflowExecutionService(
                workflow_service=service,
                tool_router=tool_router,
            )
        )

        heartbeat_calls = []
        original_heartbeat = (
            service.heartbeat_workflow
        )

        def tracked_heartbeat(
            *,
            user_id,
            workflow_id,
            claim_token,
            now=None,
        ):
            heartbeat_calls.append(
                {
                    "user_id": user_id,
                    "workflow_id": workflow_id,
                    "claim_token": claim_token,
                }
            )

            return original_heartbeat(
                user_id=user_id,
                workflow_id=workflow_id,
                claim_token=claim_token,
                now=now,
            )

        service.heartbeat_workflow = tracked_heartbeat

        result = execution_service.execute(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert result["success"] is True
        assert result["status"] == "completed"
        assert len(heartbeat_calls) >= 3
        assert len(tool_router.calls) == 1

    finally:
        teardown_runtime(
            db_engine
        )


def test_executor_stops_before_tool_execution_when_lease_is_lost(
    monkeypatch,
):
    db_engine, service = build_runtime()

    try:
        workflow = create_workflow(
            service
        )

        tool_router = FakeToolRouter()

        execution_service = (
            DurableWorkflowExecutionService(
                workflow_service=service,
                tool_router=tool_router,
            )
        )

        original_heartbeat = (
            service.heartbeat_workflow
        )

        heartbeat_calls = []

        def lost_heartbeat(
            *,
            user_id,
            workflow_id,
            claim_token,
            now=None,
        ):
            heartbeat_calls.append(
                {
                    "user_id": user_id,
                    "workflow_id": workflow_id,
                    "claim_token": claim_token,
                }
            )

            return None

        monkeypatch.setattr(
            service,
            "heartbeat_workflow",
            lost_heartbeat,
        )

        result = execution_service.execute(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert result["success"] is False

        assert (
            result["terminal_effect_owner"]
            is False
        )

        assert len(
            heartbeat_calls
        ) >= 1

        assert (
            len(tool_router.calls)
            == 0
        )

        current = service.get_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert current is not None
        assert current["status"] == "running"
        assert current["claim_token"]
        assert current["lease_until"]

        _ = original_heartbeat

    finally:
        teardown_runtime(
            db_engine
        )


def test_executor_does_not_finalize_step_after_post_tool_lease_loss(
    monkeypatch,
):
    db_engine, service = build_runtime()

    try:
        workflow = create_workflow(
            service
        )

        tool_router = FakeToolRouter()

        execution_service = (
            DurableWorkflowExecutionService(
                workflow_service=service,
                tool_router=tool_router,
            )
        )

        original_heartbeat = (
            service.heartbeat_workflow
        )

        heartbeat_count = {
            "value": 0,
        }

        def heartbeat_then_lose_lease(
            *,
            user_id,
            workflow_id,
            claim_token,
            now=None,
        ):
            heartbeat_count["value"] += 1

            if heartbeat_count["value"] == 1:
                return original_heartbeat(
                    user_id=user_id,
                    workflow_id=workflow_id,
                    claim_token=claim_token,
                    now=now,
                )

            return None

        monkeypatch.setattr(
            service,
            "heartbeat_workflow",
            heartbeat_then_lose_lease,
        )

        finish_calls = []

        original_finish_step = (
            service.finish_step
        )

        def tracked_finish_step(
            *,
            user_id,
            workflow_id,
            step_id,
            status,
            result=None,
            error=None,
            workflow_claim_token=None,
            now=None,
        ):
            finish_calls.append(
                {
                    "step_id": step_id,
                    "status": status,
                    "workflow_claim_token": (
                        workflow_claim_token
                    ),
                }
            )

            return original_finish_step(
                user_id=user_id,
                workflow_id=workflow_id,
                step_id=step_id,
                status=status,
                result=result,
                error=error,
                workflow_claim_token=(
                    workflow_claim_token
                ),
                now=now,
            )

        monkeypatch.setattr(
            service,
            "finish_step",
            tracked_finish_step,
        )

        result = execution_service.execute(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert result["success"] is False

        assert (
            result["terminal_effect_owner"]
            is False
        )

        assert (
            len(tool_router.calls)
            == 1
        )

        assert (
            len(finish_calls)
            == 0
        )

        current = service.get_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert current is not None
        assert current["status"] == "running"

        current_step = current[
            "steps"
        ][0]

        assert (
            current_step["status"]
            == "running"
        )

        assert (
            heartbeat_count["value"]
            == 2
        )

    finally:
        teardown_runtime(
            db_engine
        )