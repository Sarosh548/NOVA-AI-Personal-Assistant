import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault(
    "GROQ_API_KEY",
    "test-key",
)

from agent import graph as graph_module
from services.planner_service import (
    PlanDecision,
    PlanStep,
)
from services.plan_permission_service import (
    PlanPermissionDecision,
)


def sample_step():
    return {
        "step_id": "step-1",
        "tool": "task",
        "action": "create",
        "data": {
            "task": "practice LangGraph",
        },
        "depends_on": [],
    }


def sample_plan_decision():
    step = PlanStep(
        step_id="step-1",
        tool="task",
        action="create",
        data={
            "task": "practice LangGraph",
        },
        depends_on=(),
    )

    return PlanDecision(
        requires_tool=True,
        tool="task",
        action="create",
        data=dict(step.data),
        reason="validated",
        steps=(step,),
    )


def base_state():
    return {
        "user_id": "user-001",
        "conversation_id": 7,
        "user_message": "schedule this",
        "history": [],
        "understanding": {},
        "plan": {},
        "permission": {},
        "user_requested": True,
        "execution_context": (
            graph_module.ExecutionContext.interactive()
        ),
        "confirmation": dict(
            graph_module.DEFAULT_CONFIRMATION
        ),
        "tool_result": dict(
            graph_module.DEFAULT_TOOL_RESULT
        ),
        "workflow_result": dict(
            graph_module.DEFAULT_WORKFLOW_RESULT
        ),
        "memory_context": "",
        "response": "",
    }


class FakeAgentPlanner:
    def __init__(self, decision):
        self.decision = decision

    def create_plan(self, **kwargs):
        return self.decision


class FakePlanPermission:
    def __init__(self, decision):
        self.decision = decision
        self.user_requested = None

    def check(self, **kwargs):
        self.user_requested = kwargs["user_requested"]
        return self.decision


class FakeAutonomousWorkflowService:
    def __init__(
        self,
        workflow=None,
        validation_error=None,
    ):
        self.workflow = workflow or {
            "id": 101,
            "user_id": "user-001",
            "conversation_id": 7,
            "status": "pending",
            "execution_mode": "autonomous",
            "scheduled_at": datetime(
                2026,
                9,
                18,
                5,
                0,
            ),
            "steps": [sample_step()],
        }
        self.validation_error = validation_error
        self.validation_calls = []
        self.create_calls = []

    def validate_scheduled_at(
        self,
        value,
    ):
        self.validation_calls.append(value)

        if self.validation_error is not None:
            raise ValueError(
                self.validation_error
            )

        return datetime(
            2026,
            9,
            18,
            5,
            0,
        )

    def create_scheduled_workflow(
        self,
        **kwargs,
    ):
        self.create_calls.append(kwargs)
        return self.workflow


class FakeExecutionService:
    def execute(self, **kwargs):
        raise AssertionError(
            "Immediate workflow execution must not run for a scheduled workflow."
        )


class FakeConfirmationService:
    def __init__(
        self,
        pending=None,
        claimed=None,
    ):
        self.pending = pending
        self.claimed = claimed
        self.finished = []
        self.claim_calls = []

    def parse_response(
        self,
        message,
    ):
        return "approve"

    def get_latest_pending_confirmation(
        self,
        **kwargs,
    ):
        return self.pending

    def approve_confirmation(
        self,
        **kwargs,
    ):
        return {
            **self.pending,
            "status": "approved",
        }

    def claim_confirmation(
        self,
        **kwargs,
    ):
        self.claim_calls.append(kwargs)
        return self.claimed

    def finish_confirmation(
        self,
        **kwargs,
    ):
        self.finished.append(kwargs)

        return {
            "id": kwargs["confirmation_id"],
            "status": (
                "consumed"
                if kwargs["success"]
                else "failed"
            ),
            "tool": "workflow",
            "action": "execute",
            "reason": "test",
        }


def test_planner_marks_future_planning_request_as_autonomous(
    monkeypatch,
):
    scheduled_at = (
        "2026-09-18T10:00:00+05:00"
    )

    understanding = {
        "intent": "planning",
        "scheduled_at": scheduled_at,
        "requires_tool": True,
    }

    state = base_state()
    state["understanding"] = understanding

    monkeypatch.setattr(
        graph_module,
        "agent_planner_service",
        FakeAgentPlanner(
            sample_plan_decision()
        ),
    )

    result = graph_module.planner_node(
        state
    )

    assert (
        result["plan"]["execution_mode"]
        == "autonomous"
    )

    assert (
        result["plan"]["scheduled_at"]
        == scheduled_at
    )


def test_immediate_planning_remains_normal_workflow(
    monkeypatch,
):
    state = base_state()

    state["understanding"] = {
        "intent": "planning",
        "scheduled_at": None,
        "requires_tool": True,
    }

    monkeypatch.setattr(
        graph_module,
        "agent_planner_service",
        FakeAgentPlanner(
            sample_plan_decision()
        ),
    )

    result = graph_module.planner_node(
        state
    )

    assert (
        result["plan"]["execution_mode"]
        == "workflow"
    )

    assert (
        result["plan"]["scheduled_at"]
        is None
    )


def test_scheduled_workflow_permission_uses_autonomous_authority(
    monkeypatch,
):
    decision = PlanPermissionDecision(
        allowed=True,
        requires_confirmation=False,
        reason="allowed",
        steps=(),
    )

    fake_permission = FakePlanPermission(
        decision
    )

    fake_autonomous = (
        FakeAutonomousWorkflowService()
    )

    monkeypatch.setattr(
        graph_module,
        "plan_permission_service",
        fake_permission,
    )

    monkeypatch.setattr(
        graph_module,
        "autonomous_workflow_service",
        fake_autonomous,
    )

    state = base_state()

    state["plan"] = {
        "requires_tool": True,
        "execution_mode": "autonomous",
        "scheduled_at": (
            "2026-09-18T10:00:00+05:00"
        ),
        "steps": [sample_step()],
    }

    result = graph_module.permission_node(
        state
    )

    assert (
        fake_permission.user_requested
        is False
    )

    assert (
        result["permission"]["allowed"]
        is True
    )


def test_invalid_scheduled_workflow_is_blocked_before_permission(
    monkeypatch,
):
    decision = PlanPermissionDecision(
        allowed=True,
        requires_confirmation=False,
        reason="allowed",
        steps=(),
    )

    fake_permission = FakePlanPermission(
        decision
    )

    fake_autonomous = (
        FakeAutonomousWorkflowService(
            validation_error=(
                "Scheduled datetime must be in the future."
            )
        )
    )

    monkeypatch.setattr(
        graph_module,
        "plan_permission_service",
        fake_permission,
    )

    monkeypatch.setattr(
        graph_module,
        "autonomous_workflow_service",
        fake_autonomous,
    )

    state = base_state()

    state["plan"] = {
        "requires_tool": True,
        "execution_mode": "autonomous",
        "scheduled_at": (
            "2026-09-17T10:00:00+05:00"
        ),
        "steps": [sample_step()],
    }

    result = graph_module.permission_node(
        state
    )

    assert (
        result["permission"]["allowed"]
        is False
    )

    assert (
        result["permission"][
            "requires_confirmation"
        ]
        is False
    )

    assert (
        "must be in the future"
        in result["permission"]["reason"]
    )

    assert (
        fake_permission.user_requested
        is None
    )


def test_confirmation_approval_preserves_scheduled_autonomous_workflow(
    monkeypatch,
):
    pending = {
        "id": 55,
        "status": "pending",
        "tool": "workflow",
        "action": "execute",
        "reason": (
            "background risk requires approval"
        ),
        "data": {
            "execution_mode": "autonomous",
            "scheduled_at": (
                "2026-09-18T10:00:00+05:00"
            ),
            "steps": [sample_step()],
        },
    }

    fake_confirmation = (
        FakeConfirmationService(
            pending=pending,
        )
    )

    monkeypatch.setattr(
        graph_module,
        "confirmation_service",
        fake_confirmation,
    )

    state = base_state()
    state["user_message"] = "yes"

    result = graph_module.confirmation_node(
        state
    )

    assert (
        result["plan"]["execution_mode"]
        == "autonomous"
    )

    assert (
        result["plan"]["scheduled_at"]
        == "2026-09-18T10:00:00+05:00"
    )

    assert (
        result["plan"]["steps"]
        == [sample_step()]
    )


def test_scheduled_workflow_is_persisted_instead_of_executed(
    monkeypatch,
):
    fake_autonomous = (
        FakeAutonomousWorkflowService()
    )

    fake_confirmation = (
        FakeConfirmationService()
    )

    monkeypatch.setattr(
        graph_module,
        "autonomous_workflow_service",
        fake_autonomous,
    )

    monkeypatch.setattr(
        graph_module,
        "plan_execution_service",
        FakeExecutionService(),
    )

    monkeypatch.setattr(
        graph_module,
        "confirmation_service",
        fake_confirmation,
    )

    state = base_state()

    state["plan"] = {
        "requires_tool": True,
        "execution_mode": "autonomous",
        "scheduled_at": (
            "2026-09-18T10:00:00+05:00"
        ),
        "steps": [sample_step()],
    }

    state["permission"] = {
        "allowed": True,
        "requires_confirmation": False,
        "reason": "allowed",
    }

    result = graph_module.workflow_node(
        state
    )

    assert (
        result["workflow_result"]["success"]
        is True
    )

    assert (
        result["workflow_result"]["status"]
        == "scheduled"
    )

    assert (
        result["workflow_result"]["workflow_id"]
        == 101
    )

    assert (
        result["workflow_result"]["scheduled_at"]
        == fake_autonomous.workflow[
            "scheduled_at"
        ]
    )

    assert (
        len(fake_autonomous.create_calls)
        == 1
    )

    assert (
        fake_autonomous.create_calls[0][
            "plan"
        ]["execution_mode"]
        == "autonomous"
    )


def test_approved_scheduled_workflow_consumes_confirmation_after_persistence(
    monkeypatch,
):
    confirmation_id = 77

    claimed = {
        "id": confirmation_id,
        "status": "processing",
        "tool": "workflow",
        "action": "execute",
        "reason": "approved",
        "data": {
            "execution_mode": "autonomous",
            "scheduled_at": (
                "2026-09-18T10:00:00+05:00"
            ),
            "steps": [sample_step()],
        },
    }

    fake_confirmation = (
        FakeConfirmationService(
            claimed=claimed,
        )
    )

    fake_autonomous = (
        FakeAutonomousWorkflowService()
    )

    monkeypatch.setattr(
        graph_module,
        "confirmation_service",
        fake_confirmation,
    )

    monkeypatch.setattr(
        graph_module,
        "autonomous_workflow_service",
        fake_autonomous,
    )

    monkeypatch.setattr(
        graph_module,
        "plan_execution_service",
        FakeExecutionService(),
    )

    state = base_state()

    state["plan"] = {
        "requires_tool": True,
        "execution_mode": "autonomous",
        "scheduled_at": (
            "2026-09-18T10:00:00+05:00"
        ),
        "steps": [sample_step()],
    }

    state["permission"] = {
        "allowed": True,
        "requires_confirmation": False,
        "reason": "approved",
    }

    state["confirmation"] = {
        "id": confirmation_id,
        "status": "approved",
        "tool": "workflow",
        "action": "execute",
        "reason": "approved",
    }

    result = graph_module.workflow_node(
        state
    )

    assert (
        result["workflow_result"]["status"]
        == "scheduled"
    )

    assert (
        fake_confirmation.claim_calls
        == [
            {
                "user_id": "user-001",
                "confirmation_id": confirmation_id,
            }
        ]
    )

    assert (
        fake_confirmation.finished[-1][
            "confirmation_id"
        ]
        == confirmation_id
    )

    assert (
        fake_confirmation.finished[-1][
            "success"
        ]
        is True
    )

    assert (
        fake_autonomous.create_calls[0][
            "idempotency_key"
        ]
        == f"confirmation:{confirmation_id}"
    )