from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.workflow import Workflow
from models.workflow_step import WorkflowStep
from services.durable_workflow_execution_service import (
    DurableWorkflowExecutionService,
)
from services.workflow_service import WorkflowService
from services.workflow_execution_safety_service import (
    WorkflowExecutionSafetyDecision,
)


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


class FakeExecutionSafetyService:
    def __init__(
        self,
        decision,
    ):
        self.decision = decision
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

        return self.decision


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

    workflow_service = WorkflowService(
        db_engine=db_engine
    )

    return (
        db_engine,
        workflow_service,
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


def autonomous_step():
    return {
        "step_id": "step-1",
        "tool": "task",
        "action": "create",
        "data": {
            "task": "Run safe autonomous task",
        },
        "depends_on": [],
    }


def test_safe_autonomous_workflow_is_rechecked_and_executes():
    db_engine, workflow_service = build_runtime()

    try:
        workflow = workflow_service.create_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={
                "execution_mode": "autonomous",
            },
            steps=[
                autonomous_step()
            ],
            execution_mode="autonomous",
        )

        safety_service = (
            FakeExecutionSafetyService(
                WorkflowExecutionSafetyDecision(
                    allowed=True,
                    requires_confirmation=False,
                    reason="All steps are currently permitted.",
                    risk_levels={
                        "step-1": "medium",
                    },
                    risk_flags={
                        "step-1": (),
                    },
                )
            )
        )

        router = FakeToolRouter()

        executor = (
            DurableWorkflowExecutionService(
                workflow_service=workflow_service,
                tool_router=router,
                execution_safety_service=safety_service,
            )
        )

        result = executor.execute(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert result["status"] == "completed"
        assert result["success"] is True

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

        assert router.calls == [
            {
                "intent": "task",
                "user_id": "user-001",
                "data": {
                    "task": "Run safe autonomous task",
                },
            }
        ]

        final_state = (
            workflow_service.get_workflow(
                user_id="user-001",
                workflow_id=workflow["id"],
            )
        )

        assert final_state is not None
        assert final_state["status"] == "completed"
        assert (
            final_state["steps"][0]["status"]
            == "completed"
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_newly_risky_autonomous_workflow_is_blocked_before_tool_execution():
    db_engine, workflow_service = build_runtime()

    try:
        workflow = workflow_service.create_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={
                "execution_mode": "autonomous",
            },
            steps=[
                {
                    "step_id": "step-1",
                    "tool": "email",
                    "action": "send",
                    "data": {
                        "recipient": "client@example.com",
                    },
                    "depends_on": [],
                }
            ],
            execution_mode="autonomous",
        )

        safety_service = (
            FakeExecutionSafetyService(
                WorkflowExecutionSafetyDecision(
                    allowed=False,
                    requires_confirmation=True,
                    reason=(
                        "Step step-1 requires "
                        "explicit confirmation."
                    ),
                    risk_levels={
                        "step-1": "high",
                    },
                    risk_flags={
                        "step-1": (
                            "high_risk_action",
                            "external_communication",
                        ),
                    },
                )
            )
        )

        router = FakeToolRouter()

        executor = (
            DurableWorkflowExecutionService(
                workflow_service=workflow_service,
                tool_router=router,
                execution_safety_service=safety_service,
            )
        )

        result = executor.execute(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert result["success"] is False
        assert result["status"] == "blocked"
        assert result["workflow_id"] == workflow["id"]

        assert len(
            safety_service.calls
        ) == 1

        assert router.calls == []

        final_state = (
            workflow_service.get_workflow(
                user_id="user-001",
                workflow_id=workflow["id"],
            )
        )

        assert final_state is not None
        assert final_state["status"] == "blocked"

        assert (
            final_state["result"][
                "safety_blocked"
            ]
            is True
        )

        assert (
            "requires"
            in final_state["error"]
        )

        assert (
            final_state["steps"][0]["status"]
            == "pending"
        )

    finally:
        teardown_runtime(
            db_engine
        )