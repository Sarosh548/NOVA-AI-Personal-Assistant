from __future__ import annotations

from services.permission_service import (
    PermissionDecision,
)
from services.plan_permission_service import (
    PlanPermissionDecision,
    StepPermissionDecision,
)
from services.workflow_execution_safety_service import (
    WorkflowExecutionSafetyService,
)


def sample_steps():
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


class FakePlanPermissionService:
    def __init__(
        self,
        decision,
    ):
        self.decision = decision
        self.user_requested = None
        self.user_id = None
        self.steps = None

    def check(
        self,
        *,
        user_id,
        steps,
        user_requested,
    ):
        self.user_id = user_id
        self.steps = steps
        self.user_requested = user_requested
        return self.decision


def test_safe_workflow_is_allowed_with_autonomous_authority():
    fake = FakePlanPermissionService(
        PlanPermissionDecision(
            allowed=True,
            requires_confirmation=False,
            reason="All steps permitted.",
            steps=(
                StepPermissionDecision(
                    step_id="step-1",
                    tool="task",
                    action="create",
                    allowed=True,
                    requires_confirmation=False,
                    reason="Allowed.",
                    risk_level="medium",
                    risk_flags=(),
                ),
            ),
        )
    )

    service = WorkflowExecutionSafetyService(
        plan_permission_service=fake,
    )

    result = service.check(
        user_id="user-001",
        steps=sample_steps(),
    )

    assert result.allowed is True
    assert result.requires_confirmation is False
    assert result.risk_levels == {
        "step-1": "medium",
    }
    assert result.risk_flags == {
        "step-1": (),
    }

    assert fake.user_id == "user-001"
    assert fake.user_requested is False


def test_newly_risky_workflow_requires_confirmation():
    fake = FakePlanPermissionService(
        PlanPermissionDecision(
            allowed=False,
            requires_confirmation=True,
            reason="Step step-1 requires confirmation.",
            steps=(
                StepPermissionDecision(
                    step_id="step-1",
                    tool="email",
                    action="send",
                    allowed=False,
                    requires_confirmation=True,
                    reason="High-risk action.",
                    risk_level="high",
                    risk_flags=(
                        "high_risk_action",
                        "external_communication",
                    ),
                ),
            ),
        )
    )

    service = WorkflowExecutionSafetyService(
        plan_permission_service=fake,
    )

    result = service.check(
        user_id="user-001",
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
    )

    assert result.allowed is False
    assert result.requires_confirmation is True

    assert result.risk_levels == {
        "step-1": "high",
    }

    assert result.risk_flags == {
        "step-1": (
            "high_risk_action",
            "external_communication",
        ),
    }

    assert fake.user_requested is False


def test_denied_workflow_is_not_allowed():
    fake = FakePlanPermissionService(
        PlanPermissionDecision(
            allowed=False,
            requires_confirmation=False,
            reason="The workflow is denied.",
            steps=(
                StepPermissionDecision(
                    step_id="step-1",
                    tool="task",
                    action="delete",
                    allowed=False,
                    requires_confirmation=False,
                    reason="Denied.",
                    risk_level="medium",
                    risk_flags=(),
                ),
            ),
        )
    )

    service = WorkflowExecutionSafetyService(
        plan_permission_service=fake,
    )

    result = service.check(
        user_id="user-001",
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "delete",
                "data": {},
                "depends_on": [],
            }
        ],
    )

    assert result.allowed is False
    assert result.requires_confirmation is False
    assert result.reason == (
        "The workflow is denied."
    )


def test_missing_user_id_is_rejected():
    fake = FakePlanPermissionService(
        PlanPermissionDecision(
            allowed=True,
            requires_confirmation=False,
            reason="Should not execute.",
            steps=(),
        )
    )

    service = WorkflowExecutionSafetyService(
        plan_permission_service=fake,
    )

    result = service.check(
        user_id="   ",
        steps=sample_steps(),
    )

    assert result.allowed is False
    assert result.requires_confirmation is False
    assert result.reason == (
        "Workflow user_id is missing."
    )

    assert fake.user_requested is None


def test_invalid_steps_are_rejected():
    fake = FakePlanPermissionService(
        PlanPermissionDecision(
            allowed=True,
            requires_confirmation=False,
            reason="Should not execute.",
            steps=(),
        )
    )

    service = WorkflowExecutionSafetyService(
        plan_permission_service=fake,
    )

    result = service.check(
        user_id="user-001",
        steps={},
    )

    assert result.allowed is False
    assert result.requires_confirmation is False
    assert result.reason == (
        "Workflow steps must be provided as a list."
    )

    assert fake.user_requested is None