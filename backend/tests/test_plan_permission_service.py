from services.plan_permission_service import (
    PlanPermissionService,
)
from services.permission_service import (
    PermissionDecision,
)
from services.planner_service import (
    PlanStep,
)


class FakePermissionService:
    """
    Safe in-memory PermissionService replacement.

    No database is accessed.
    """

    def __init__(
        self,
        decisions=None,
    ):
        self.decisions = decisions or {}
        self.calls = []

    def check(
        self,
        user_id,
        tool,
        action,
        user_requested=False,
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "tool": tool,
                "action": action,
                "user_requested": user_requested,
            }
        )

        return self.decisions.get(
            (tool, action),
            PermissionDecision(
                allowed=True,
                requires_confirmation=False,
                reason="Allowed.",
            ),
        )


def test_empty_workflow_is_allowed():
    permission_service = FakePermissionService()

    service = PlanPermissionService(
        permission_service=permission_service
    )

    result = service.check(
        user_id="user-001",
        steps=[],
        user_requested=True,
    )

    assert result.allowed is True
    assert result.requires_confirmation is False
    assert result.steps == ()
    assert (
        "no executable steps"
        in result.reason.lower()
    )

    assert permission_service.calls == []


def test_all_allowed_steps_allow_entire_workflow():
    permission_service = FakePermissionService()

    service = PlanPermissionService(
        permission_service=permission_service
    )

    result = service.check(
        user_id="user-001",
        steps=[
            PlanStep(
                step_id="step-1",
                tool="task",
                action="list",
                data={},
            ),
            PlanStep(
                step_id="step-2",
                tool="reminder",
                action="list",
                data={},
                depends_on=(
                    "step-1",
                ),
            ),
        ],
        user_requested=False,
    )

    assert result.allowed is True
    assert result.requires_confirmation is False
    assert result.reason == (
        "All steps in the workflow are permitted to execute."
    )

    assert len(result.steps) == 2

    assert all(
        step.allowed is True
        for step in result.steps
    )

    assert all(
        step.requires_confirmation is False
        for step in result.steps
    )

    assert len(permission_service.calls) == 2


def test_any_confirmation_required_step_requires_whole_workflow_confirmation():
    permission_service = FakePermissionService(
        decisions={
            (
                "task",
                "list",
            ): PermissionDecision(
                allowed=True,
                requires_confirmation=False,
                reason="Read-only action is allowed.",
            ),
            (
                "task",
                "delete",
            ): PermissionDecision(
                allowed=False,
                requires_confirmation=True,
                reason="Delete requires confirmation.",
            ),
        }
    )

    service = PlanPermissionService(
        permission_service=permission_service
    )

    result = service.check(
        user_id="user-001",
        steps=[
            PlanStep(
                step_id="step-1",
                tool="task",
                action="list",
                data={},
            ),
            PlanStep(
                step_id="step-2",
                tool="task",
                action="delete",
                data={
                    "task_id": 20,
                },
                depends_on=(
                    "step-1",
                ),
            ),
        ],
        user_requested=False,
    )

    assert result.allowed is False
    assert result.requires_confirmation is True

    assert (
        "step-2"
        in result.reason
    )

    assert result.steps[0].allowed is True
    assert (
        result.steps[0].requires_confirmation
        is False
    )

    assert result.steps[1].allowed is False
    assert (
        result.steps[1].requires_confirmation
        is True
    )


def test_denied_step_blocks_entire_workflow():
    permission_service = FakePermissionService(
        decisions={
            (
                "task",
                "delete",
            ): PermissionDecision(
                allowed=False,
                requires_confirmation=False,
                reason="Action is denied.",
            )
        }
    )

    service = PlanPermissionService(
        permission_service=permission_service
    )

    result = service.check(
        user_id="user-001",
        steps=[
            PlanStep(
                step_id="step-1",
                tool="task",
                action="list",
                data={},
            ),
            PlanStep(
                step_id="step-2",
                tool="task",
                action="delete",
                data={
                    "task_id": 20,
                },
            ),
        ],
        user_requested=False,
    )

    assert result.allowed is False
    assert result.requires_confirmation is False

    assert (
        "step-2"
        in result.reason
    )

    assert (
        result.steps[1].allowed
        is False
    )

    assert (
        result.steps[1]
        .requires_confirmation
        is False
    )


def test_denial_takes_priority_over_confirmation():
    permission_service = FakePermissionService(
        decisions={
            (
                "task",
                "delete",
            ): PermissionDecision(
                allowed=False,
                requires_confirmation=False,
                reason="Action is denied.",
            ),
            (
                "task",
                "complete",
            ): PermissionDecision(
                allowed=False,
                requires_confirmation=True,
                reason="Confirmation required.",
            ),
        }
    )

    service = PlanPermissionService(
        permission_service=permission_service
    )

    result = service.check(
        user_id="user-001",
        steps=[
            PlanStep(
                step_id="step-1",
                tool="task",
                action="delete",
                data={},
            ),
            PlanStep(
                step_id="step-2",
                tool="task",
                action="complete",
                data={},
            ),
        ],
        user_requested=False,
    )

    assert result.allowed is False
    assert result.requires_confirmation is False
    assert (
        "denied"
        in result.reason.lower()
    )


def test_explicit_interactive_request_can_allow_state_changes():
    permission_service = FakePermissionService(
        decisions={
            (
                "task",
                "delete",
            ): PermissionDecision(
                allowed=True,
                requires_confirmation=False,
                reason="Explicit user request.",
            ),
            (
                "reminder",
                "update",
            ): PermissionDecision(
                allowed=True,
                requires_confirmation=False,
                reason="Explicit user request.",
            ),
        }
    )

    service = PlanPermissionService(
        permission_service=permission_service
    )

    result = service.check(
        user_id="user-001",
        steps=[
            PlanStep(
                step_id="step-1",
                tool="task",
                action="delete",
                data={
                    "task_id": 10,
                },
            ),
            PlanStep(
                step_id="step-2",
                tool="reminder",
                action="update",
                data={
                    "reminder_id": 5,
                },
            ),
        ],
        user_requested=True,
    )

    assert result.allowed is True
    assert result.requires_confirmation is False

    assert all(
        step.allowed is True
        for step in result.steps
    )


def test_dictionary_steps_are_supported():
    permission_service = FakePermissionService()

    service = PlanPermissionService(
        permission_service=permission_service
    )

    result = service.check(
        user_id="user-001",
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "list",
                "data": {},
                "depends_on": [],
            }
        ],
        user_requested=False,
    )

    assert result.allowed is True
    assert result.requires_confirmation is False

    assert result.steps[0].step_id == "step-1"
    assert result.steps[0].tool == "task"
    assert result.steps[0].action == "list"


def test_invalid_step_blocks_workflow():
    permission_service = FakePermissionService()

    service = PlanPermissionService(
        permission_service=permission_service
    )

    result = service.check(
        user_id="user-001",
        steps=[
            {
                "step_id": "step-1",
                "tool": "",
                "action": "list",
                "data": {},
            }
        ],
        user_requested=True,
    )

    assert result.allowed is False
    assert result.requires_confirmation is False
    assert result.steps == ()
    assert (
        "invalid plan step"
        in result.reason.lower()
    )

    assert permission_service.calls == []


def test_non_boolean_user_requested_blocks_workflow():
    permission_service = FakePermissionService()

    service = PlanPermissionService(
        permission_service=permission_service
    )

    result = service.check(
        user_id="user-001",
        steps=[
            PlanStep(
                step_id="step-1",
                tool="task",
                action="list",
                data={},
            )
        ],
        user_requested="yes",
    )

    assert result.allowed is False
    assert result.requires_confirmation is False
    assert result.steps == ()
    assert (
        "boolean"
        in result.reason.lower()
    )


def test_permission_service_receives_correct_user_context():
    permission_service = FakePermissionService()

    service = PlanPermissionService(
        permission_service=permission_service
    )

    service.check(
        user_id="specific-user",
        steps=[
            PlanStep(
                step_id="step-1",
                tool="task",
                action="list",
                data={},
            )
        ],
        user_requested=False,
    )

    assert permission_service.calls == [
        {
            "user_id": "specific-user",
            "tool": "task",
            "action": "list",
            "user_requested": False,
        }
    ]