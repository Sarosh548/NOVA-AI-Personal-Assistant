from agent import graph
from services.confirmation_execution_service import (
    ConfirmationExecutionService,
)


class FakePlanPermissionService:
    def __init__(
        self,
        allowed=True,
        requires_confirmation=False,
        reason="Allowed.",
    ):
        self.allowed = allowed
        self.requires_confirmation = (
            requires_confirmation
        )
        self.reason = reason
        self.calls = []

    def check(
        self,
        *,
        user_id,
        steps,
        user_requested,
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "steps": steps,
                "user_requested": user_requested,
            }
        )

        from services.plan_permission_service import (
            PlanPermissionDecision,
            StepPermissionDecision,
        )

        step_decisions = tuple(
            StepPermissionDecision(
                step_id=step["step_id"],
                tool=step["tool"],
                action=step["action"],
                allowed=self.allowed,
                requires_confirmation=(
                    self.requires_confirmation
                ),
                reason=self.reason,
            )
            for step in steps
        )

        return PlanPermissionDecision(
            allowed=self.allowed,
            requires_confirmation=(
                self.requires_confirmation
            ),
            reason=self.reason,
            steps=step_decisions,
        )


class FakeConfirmationService:
    def __init__(
        self,
        pending=None,
        response_type=None,
    ):
        self.pending = pending
        self.response_type = response_type
        self.created = []
        self.approved = []
        self.rejected = []
        self.claimed = []
        self.finished = []

    def parse_response(
        self,
        message,
    ):
        return self.response_type

    def get_latest_pending_confirmation(
        self,
        user_id,
        conversation_id=None,
    ):
        return self.pending

    def create_confirmation(
        self,
        user_id,
        conversation_id,
        tool,
        action,
        data,
        reason,
    ):
        self.created.append(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "tool": tool,
                "action": action,
                "data": data,
                "reason": reason,
            }
        )

        return 900

    def approve_confirmation(
        self,
        user_id,
        confirmation_id,
    ):
        self.approved.append(
            confirmation_id
        )

        result = dict(
            self.pending
        )

        result["status"] = "approved"

        return result

    def reject_confirmation(
        self,
        user_id,
        confirmation_id,
    ):
        self.rejected.append(
            confirmation_id
        )

        result = dict(
            self.pending
        )

        result["status"] = "rejected"

        return result

    def claim_confirmation(
        self,
        user_id,
        confirmation_id,
    ):
        if confirmation_id in self.claimed:
            return None

        self.claimed.append(
            confirmation_id
        )

        result = dict(
            self.pending
        )

        result["status"] = "processing"

        return result

    def finish_confirmation(
        self,
        user_id,
        confirmation_id,
        success,
    ):
        self.finished.append(
            {
                "user_id": user_id,
                "confirmation_id": confirmation_id,
                "success": success,
            }
        )

        result = dict(
            self.pending
        )

        result["status"] = (
            "consumed"
            if success
            else "failed"
        )

        return result


class FakePlanExecutionService:
    def __init__(
        self,
        success=True,
    ):
        self.success = success
        self.calls = []

    def execute(
        self,
        *,
        user_id,
        steps,
    ):
        from services.plan_execution_service import (
            PlanExecutionResult,
            StepExecutionResult,
        )

        self.calls.append(
            {
                "user_id": user_id,
                "steps": steps,
            }
        )

        step_results = tuple(
            StepExecutionResult(
                step_id=step["step_id"],
                tool=step["tool"],
                action=step["action"],
                status=(
                    "completed"
                    if self.success
                    else "failed"
                ),
                result={
                    "message": "test result",
                },
                error=(
                    None
                    if self.success
                    else "test failure"
                ),
            )
            for step in steps
        )

        return PlanExecutionResult(
            success=self.success,
            status=(
                "completed"
                if self.success
                else "partial"
            ),
            steps=step_results,
            error=(
                None
                if self.success
                else "One or more steps failed."
            ),
        )


def _workflow_plan():
    return {
        "requires_tool": True,
        "execution_mode": "workflow",
        "tool": None,
        "action": None,
        "data": {},
        "reason": "Validated workflow.",
        "steps": [
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "list",
                "data": {},
                "depends_on": [],
            },
            {
                "step_id": "step-2",
                "tool": "reminder",
                "action": "create",
                "data": {
                    "reminder_action": "create",
                    "task": "Review tasks",
                    "scheduled_at": (
                        "2026-09-18T20:00:00+05:00"
                    ),
                },
                "depends_on": [
                    "step-1"
                ],
            },
        ],
    }


def _base_state():
    return {
        "user_id": "user-001",
        "conversation_id": 100,
        "user_message": "Organize my work.",
        "history": [],
        "understanding": {
            "intent": "planning",
            "requires_tool": True,
        },
        "plan": _workflow_plan(),
        "permission": {},
        "user_requested": True,
        "execution_context": None,
        "confirmation": {
            "id": None,
            "status": None,
            "tool": None,
            "action": None,
            "reason": None,
        },
        "tool_result": {},
        "workflow_result": {},
        "memory_context": "",
        "response": "",
    }


def test_workflow_permission_allows_interactive_plan(
    monkeypatch,
):
    fake_permission = FakePlanPermissionService(
        allowed=True,
        requires_confirmation=False,
        reason="All workflow steps are allowed.",
    )

    monkeypatch.setattr(
        graph,
        "plan_permission_service",
        fake_permission,
    )

    state = _base_state()

    result = graph.permission_node(
        state
    )

    assert result["permission"]["allowed"] is True

    assert (
        result["permission"]
        ["requires_confirmation"]
        is False
    )

    assert (
        result["confirmation"]["id"]
        is None
    )

    assert len(fake_permission.calls) == 1
    assert (
        fake_permission.calls[0]["user_id"]
        == "user-001"
    )

    assert (
        len(fake_permission.calls[0]["steps"])
        == 2
    )


def test_workflow_permission_creates_single_confirmation_for_background_plan(
    monkeypatch,
):
    fake_permission = FakePlanPermissionService(
        allowed=False,
        requires_confirmation=True,
        reason=(
            "The workflow requires confirmation."
        ),
    )

    fake_confirmation = FakeConfirmationService()

    monkeypatch.setattr(
        graph,
        "plan_permission_service",
        fake_permission,
    )

    monkeypatch.setattr(
        graph,
        "confirmation_service",
        fake_confirmation,
    )

    state = _base_state()
    state["user_requested"] = False

    result = graph.permission_node(
        state
    )

    assert result["permission"]["allowed"] is False

    assert (
        result["permission"]
        ["requires_confirmation"]
        is True
    )

    assert (
        result["confirmation"]["tool"]
        == "workflow"
    )

    assert (
        result["confirmation"]["action"]
        == "execute"
    )

    assert (
        result["confirmation"]["status"]
        == "pending"
    )

    assert len(fake_confirmation.created) == 1

    created = fake_confirmation.created[0]

    assert created["tool"] == "workflow"
    assert created["action"] == "execute"

    assert (
        created["data"]["execution_mode"]
        == "workflow"
    )

    assert (
        created["data"]["steps"]
        == state["plan"]["steps"]
    )

    assert (
        graph.route_after_permission(
            result
        )
        == "agent"
    )


def test_workflow_permission_denial_blocks_execution(
    monkeypatch,
):
    fake_permission = FakePlanPermissionService(
        allowed=False,
        requires_confirmation=False,
        reason="Workflow is denied.",
    )

    monkeypatch.setattr(
        graph,
        "plan_permission_service",
        fake_permission,
    )

    state = _base_state()

    result = graph.permission_node(
        state
    )

    assert result["permission"]["allowed"] is False

    assert (
        result["permission"]
        ["requires_confirmation"]
        is False
    )

    assert (
        graph.route_after_permission(
            result
        )
        == "agent"
    )


def test_workflow_node_executes_validated_steps(
    monkeypatch,
):
    fake_execution = FakePlanExecutionService(
        success=True
    )

    monkeypatch.setattr(
        graph,
        "plan_execution_service",
        fake_execution,
    )

    state = _base_state()

    state["permission"] = {
        "allowed": True,
        "requires_confirmation": False,
        "reason": "Allowed.",
    }

    result = graph.workflow_node(
        state
    )

    assert (
        result["workflow_result"]
        ["success"]
        is True
    )

    assert (
        result["workflow_result"]
        ["status"]
        == "completed"
    )

    assert (
        len(
            result["workflow_result"]
            ["steps"]
        )
        == 2
    )

    assert len(
        fake_execution.calls
    ) == 1

    assert (
        fake_execution.calls[0]["user_id"]
        == "user-001"
    )

    assert (
        fake_execution.calls[0]["steps"]
        == state["plan"]["steps"]
    )


def test_approved_workflow_rebuilds_exact_saved_steps(
    monkeypatch,
):
    fake_confirmation = FakeConfirmationService(
        pending={
            "id": 901,
            "status": "pending",
            "tool": "workflow",
            "action": "execute",
            "data": {
                "execution_mode": "workflow",
                "steps": [
                    {
                        "step_id": "saved-1",
                        "tool": "task",
                        "action": "list",
                        "data": {},
                        "depends_on": [],
                    },
                    {
                        "step_id": "saved-2",
                        "tool": "reminder",
                        "action": "list",
                        "data": {},
                        "depends_on": [
                            "saved-1"
                        ],
                    },
                ],
            },
            "reason": "Workflow confirmation.",
        },
        response_type="approve",
    )

    monkeypatch.setattr(
        graph,
        "confirmation_service",
        fake_confirmation,
    )

    state = _base_state()
    state["user_message"] = "yes"

    result = graph.confirmation_node(
        state
    )

    assert (
        result["confirmation"]["status"]
        == "approved"
    )

    assert (
        result["plan"]["execution_mode"]
        == "workflow"
    )

    assert (
        result["plan"]["steps"]
        == fake_confirmation.pending["data"]
        ["steps"]
    )

    assert (
        graph.route_after_confirmation(
            result
        )
        == "workflow"
    )


def test_approved_workflow_uses_saved_steps_and_finishes_once(
    monkeypatch,
):
    fake_confirmation = FakeConfirmationService(
        pending={
            "id": 902,
            "status": "pending",
            "tool": "workflow",
            "action": "execute",
            "data": {
                "execution_mode": "workflow",
                "steps": [
                    {
                        "step_id": "saved-1",
                        "tool": "task",
                        "action": "list",
                        "data": {},
                        "depends_on": [],
                    },
                    {
                        "step_id": "saved-2",
                        "tool": "reminder",
                        "action": "list",
                        "data": {},
                        "depends_on": [
                            "saved-1"
                        ],
                    },
                ],
            },
            "reason": "Workflow confirmation.",
        },
        response_type="approve",
    )

    fake_execution = FakePlanExecutionService(
        success=True
    )

    monkeypatch.setattr(
        graph,
        "confirmation_service",
        fake_confirmation,
    )

    monkeypatch.setattr(
        graph,
        "plan_execution_service",
        fake_execution,
    )

    execution_service = ConfirmationExecutionService(
        confirmation_service=fake_confirmation,
        plan_execution_service=fake_execution,
    )

    monkeypatch.setattr(
        graph,
        "confirmation_execution_service",
        execution_service,
    )

    state = _base_state()
    state["user_message"] = "yes"

    confirmed = graph.confirmation_node(
        state
    )

    executed = graph.workflow_node(
        confirmed
    )

    assert (
        executed["workflow_result"]
        ["success"]
        is True
    )

    assert (
        executed["confirmation"]
        ["status"]
        == "consumed"
    )

    assert fake_confirmation.claimed == [
        902
    ]

    assert fake_confirmation.finished == [
        {
            "user_id": "user-001",
            "confirmation_id": 902,
            "success": True,
        }
    ]

    assert len(
        fake_execution.calls
    ) == 1

    assert (
        fake_execution.calls[0]["steps"]
        == fake_confirmation.pending["data"]
        ["steps"]
    )


def test_replayed_workflow_confirmation_cannot_execute_again(
    monkeypatch,
):
    fake_confirmation = FakeConfirmationService(
        pending={
            "id": 903,
            "status": "approved",
            "tool": "workflow",
            "action": "execute",
            "data": {
                "execution_mode": "workflow",
                "steps": [
                    {
                        "step_id": "saved-1",
                        "tool": "task",
                        "action": "list",
                        "data": {},
                        "depends_on": [],
                    }
                ],
            },
            "reason": "Workflow confirmation.",
        }
    )

    fake_execution = FakePlanExecutionService(
        success=True
    )

    monkeypatch.setattr(
        graph,
        "confirmation_service",
        fake_confirmation,
    )

    monkeypatch.setattr(
        graph,
        "plan_execution_service",
        fake_execution,
    )

    execution_service = ConfirmationExecutionService(
        confirmation_service=fake_confirmation,
        plan_execution_service=fake_execution,
    )

    monkeypatch.setattr(
        graph,
        "confirmation_execution_service",
        execution_service,
    )

    state = _base_state()

    state["permission"] = {
        "allowed": True,
        "requires_confirmation": False,
        "reason": "Approved.",
    }

    state["confirmation"] = {
        "id": 903,
        "status": "approved",
        "tool": "workflow",
        "action": "execute",
        "reason": "Workflow confirmation.",
    }

    first = graph.workflow_node(
        state
    )

    second = graph.workflow_node(
        state
    )

    assert (
        first["workflow_result"]
        ["success"]
        is True
    )

    assert (
        second["workflow_result"]
        ["success"]
        is False
    )

    assert (
        "no longer available"
        in second["workflow_result"]
        ["error"]
    )

    assert len(
        fake_execution.calls
    ) == 1