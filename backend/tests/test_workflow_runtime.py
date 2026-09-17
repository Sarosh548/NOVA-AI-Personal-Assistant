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
    def __init__(
        self,
        outcomes=None,
    ):
        self.outcomes = (
            outcomes
            if outcomes is not None
            else {}
        )
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

        outcome = self.outcomes.get(
            intent,
            True,
        )

        if callable(outcome):
            return outcome()

        if outcome is True:
            return {
                "success": True,
                "tool": intent,
                "action": data.get(
                    "action",
                    "unknown",
                ),
                "result": {
                    "executed": True,
                },
                "error": None,
            }

        return {
            "success": False,
            "tool": intent,
            "action": data.get(
                "action",
                "unknown",
            ),
            "result": {},
            "error": "Simulated failure.",
        }


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


def sample_steps():
    return [
        {
            "step_id": "step-1",
            "tool": "task",
            "action": "create",
            "data": {
                "task": "Study LangGraph"
            },
            "depends_on": [],
        },
        {
            "step_id": "step-2",
            "tool": "reminder",
            "action": "create",
            "data": {
                "task": "Practice LangGraph",
            },
            "depends_on": [
                "step-1"
            ],
        },
    ]


def test_create_workflow_persists_plan_and_steps():
    db_engine, service = build_runtime()

    try:
        workflow = service.create_workflow(
            user_id="user-001",
            conversation_id=10,
            plan={
                "execution_mode": "workflow",
                "requires_tool": True,
            },
            steps=sample_steps(),
        )

        assert workflow["id"] is not None
        assert workflow["status"] == "pending"
        assert len(workflow["steps"]) == 2

        assert (
            workflow["steps"][0]["step_id"]
            == "step-1"
        )

        assert (
            workflow["steps"][1]["depends_on"]
            == ["step-1"]
        )
    finally:
        teardown_runtime(db_engine)


def test_idempotency_returns_existing_workflow():
    db_engine, service = build_runtime()

    try:
        first = service.create_workflow(
            user_id="user-001",
            conversation_id=10,
            plan={},
            steps=sample_steps(),
            idempotency_key="chat-10-workflow",
        )

        second = service.create_workflow(
            user_id="user-001",
            conversation_id=10,
            plan={
                "different": True
            },
            steps=sample_steps(),
            idempotency_key="chat-10-workflow",
        )

        assert first["id"] == second["id"]
        assert (
            second["plan"]
            == first["plan"]
        )
    finally:
        teardown_runtime(db_engine)


def test_workflow_claim_is_atomic():
    db_engine, service = build_runtime()

    try:
        workflow = service.create_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={},
            steps=sample_steps(),
        )

        first_claim = service.claim_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        second_claim = service.claim_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert first_claim is not None
        assert first_claim["status"] == "running"
        assert second_claim is None
    finally:
        teardown_runtime(db_engine)


def test_step_claim_is_atomic_and_tracks_attempts():
    db_engine, service = build_runtime()

    try:
        workflow = service.create_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={},
            steps=sample_steps(),
        )

        service.claim_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        first_claim = service.claim_step(
            user_id="user-001",
            workflow_id=workflow["id"],
            step_id="step-1",
        )

        second_claim = service.claim_step(
            user_id="user-001",
            workflow_id=workflow["id"],
            step_id="step-1",
        )

        assert first_claim is not None
        assert first_claim["status"] == "running"
        assert first_claim["attempts"] == 1
        assert second_claim is None
    finally:
        teardown_runtime(db_engine)


def test_workflow_can_finish_successfully():
    db_engine, service = build_runtime()

    try:
        workflow = service.create_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={},
            steps=sample_steps(),
        )

        service.claim_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        step1 = service.claim_step(
            user_id="user-001",
            workflow_id=workflow["id"],
            step_id="step-1",
        )

        service.finish_step(
            user_id="user-001",
            workflow_id=workflow["id"],
            step_id="step-1",
            status="completed",
            result={
                "task_id": 1
            },
        )

        step2 = service.claim_step(
            user_id="user-001",
            workflow_id=workflow["id"],
            step_id="step-2",
        )

        service.finish_step(
            user_id="user-001",
            workflow_id=workflow["id"],
            step_id="step-2",
            status="completed",
            result={
                "reminder_id": 2
            },
        )

        final = service.recalculate_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert step1 is not None
        assert step2 is not None
        assert final is not None
        assert final["status"] == "completed"
        assert final["result"]["success"] is True
    finally:
        teardown_runtime(db_engine)


def test_durable_executor_resumes_after_partial_failure():
    db_engine, service = build_runtime()

    try:
        router = FakeToolRouter(
            outcomes={
                "task": False,
                "reminder": True,
            }
        )

        executor = (
            DurableWorkflowExecutionService(
                workflow_service=service,
                tool_router=router,
            )
        )

        workflow = service.create_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={
                "execution_mode": "workflow"
            },
            steps=[
                {
                    "step_id": "step-1",
                    "tool": "task",
                    "action": "create",
                    "data": {
                        "task": "Create task"
                    },
                    "depends_on": [],
                },
                {
                    "step_id": "step-2",
                    "tool": "reminder",
                    "action": "create",
                    "data": {
                        "task": "Create reminder"
                    },
                    "depends_on": [],
                },
            ],
        )

        first_result = executor.execute(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert (
            first_result["status"]
            == "partial"
        )

        first_state = service.get_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert first_state is not None

        assert (
            first_state["steps"][0]["status"]
            == "failed"
        )

        assert (
            first_state["steps"][1]["status"]
            == "completed"
        )

        attempts_before = (
            first_state["steps"][0][
                "attempts"
            ]
        )

        router.outcomes["task"] = True

        second_result = executor.execute(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        final_state = service.get_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert second_result["status"] == "completed"
        assert final_state is not None

        assert all(
            step["status"] == "completed"
            for step in final_state["steps"]
        )

        assert (
            final_state["steps"][0][
                "attempts"
            ]
            == attempts_before + 1
        )

        assert len(router.calls) == 3
    finally:
        teardown_runtime(db_engine)


def test_dependent_step_is_skipped_after_dependency_failure():
    db_engine, service = build_runtime()

    try:
        router = FakeToolRouter(
            outcomes={
                "task": False,
                "reminder": True,
            }
        )

        executor = (
            DurableWorkflowExecutionService(
                workflow_service=service,
                tool_router=router,
            )
        )

        workflow = service.create_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={
                "execution_mode": "workflow"
            },
            steps=[
                {
                    "step_id": "step-1",
                    "tool": "task",
                    "action": "create",
                    "data": {},
                    "depends_on": [],
                },
                {
                    "step_id": "step-2",
                    "tool": "reminder",
                    "action": "create",
                    "data": {},
                    "depends_on": [
                        "step-1"
                    ],
                },
            ],
        )

        result = executor.execute(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        state = service.get_workflow(
            user_id="user-001",
            workflow_id=workflow["id"],
        )

        assert result["status"] == "failed"
        assert state is not None
        assert (
            state["steps"][0]["status"]
            == "failed"
        )
        assert (
            state["steps"][1]["status"]
            == "skipped"
        )

        assert len(router.calls) == 1
    finally:
        teardown_runtime(db_engine)