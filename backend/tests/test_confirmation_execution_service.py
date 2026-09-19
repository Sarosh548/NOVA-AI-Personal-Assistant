from __future__ import annotations

from datetime import datetime


class FakeConfirmationService:
    def __init__(
        self,
        claimed=None,
        finished=None,
    ):
        self.claimed = claimed
        self.finished = finished
        self.claim_calls = []
        self.approve_and_claim_calls = []
        self.finish_calls = []

    def approve_and_claim_confirmation(
        self,
        *,
        user_id,
        confirmation_id,
    ):
        self.approve_and_claim_calls.append(
            {
                "user_id": user_id,
                "confirmation_id": confirmation_id,
            }
        )

        if self.claimed is None:
            return None

        return dict(
            self.claimed
        )

    def claim_confirmation(
        self,
        *,
        user_id,
        confirmation_id,
    ):
        self.claim_calls.append(
            {
                "user_id": user_id,
                "confirmation_id": confirmation_id,
            }
        )

        if self.claimed is None:
            return None

        return dict(
            self.claimed
        )

    def finish_confirmation(
        self,
        *,
        user_id,
        confirmation_id,
        success,
    ):
        self.finish_calls.append(
            {
                "user_id": user_id,
                "confirmation_id": confirmation_id,
                "success": success,
            }
        )

        if self.finished is None:
            return None

        return dict(
            self.finished
        )


class FakeToolRouter:
    def __init__(
        self,
        result=None,
        raises=False,
    ):
        self.result = (
            result
            if result is not None
            else {
                "success": True,
                "tool": "task",
                "action": "create",
                "result": {
                    "task_id": 55,
                },
                "error": None,
            }
        )

        self.raises = raises
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
                "data": data,
            }
        )

        if self.raises:
            raise RuntimeError(
                "simulated tool failure"
            )

        return dict(
            self.result
        )


class FakePlanExecutionService:
    def __init__(
        self,
        result=None,
    ):
        self.result = result or _execution_result()
        self.calls = []

    def execute(
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

        return self.result


class FakeAutonomousWorkflowService:
    def __init__(
        self,
        workflow=None,
        raises=False,
    ):
        self.workflow = workflow or {
            "id": 88,
            "user_id": "user-001",
            "conversation_id": 7,
            "status": "pending",
            "execution_mode": "autonomous",
            "scheduled_at": datetime(
                2026,
                9,
                20,
                10,
                0,
            ),
            "steps": [],
        }

        self.raises = raises
        self.calls = []

    def create_scheduled_workflow(
        self,
        **kwargs,
    ):
        self.calls.append(
            kwargs
        )

        if self.raises:
            raise ValueError(
                "simulated schedule failure"
            )

        return dict(
            self.workflow
        )


def _execution_result():
    from services.plan_execution_service import (
        PlanExecutionResult,
        StepExecutionResult,
    )

    return PlanExecutionResult(
        success=True,
        status="completed",
        steps=(
            StepExecutionResult(
                step_id="step-1",
                tool="task",
                action="create",
                status="completed",
                result={
                    "task_id": 55,
                },
                error=None,
            ),
        ),
        error=None,
    )


def _build_service(
    *,
    claimed,
    finished=None,
    tool_router=None,
    plan_execution_service=None,
    autonomous_workflow_service=None,
):
    from services.confirmation_execution_service import (
        ConfirmationExecutionService,
    )

    confirmation_service = FakeConfirmationService(
        claimed=claimed,
        finished=finished,
    )

    service = ConfirmationExecutionService(
        confirmation_service=confirmation_service,
        tool_router=(
            tool_router
            if tool_router is not None
            else FakeToolRouter()
        ),
        plan_execution_service=(
            plan_execution_service
            if plan_execution_service is not None
            else FakePlanExecutionService()
        ),
        autonomous_workflow_service=(
            autonomous_workflow_service
            if autonomous_workflow_service is not None
            else FakeAutonomousWorkflowService()
        ),
    )

    return service, confirmation_service


def _confirmed_tool(
    *,
    data=None,
):
    return {
        "id": 101,
        "user_id": "user-001",
        "conversation_id": 7,
        "tool": "task",
        "action": "create",
        "data": (
            data
            if data is not None
            else {
                "task": "Practice NOVA",
            }
        ),
        "reason": "Create this task?",
        "status": "processing",
        "created_at": datetime(
            2026,
            9,
            19,
            9,
            0,
        ),
        "expires_at": datetime(
            2026,
            9,
            19,
            9,
            5,
        ),
        "resolved_at": None,
    }


def _confirmed_workflow(
    *,
    execution_mode="workflow",
):
    return {
        "id": 102,
        "user_id": "user-001",
        "conversation_id": 7,
        "tool": "workflow",
        "action": "execute",
        "data": {
            "execution_mode": execution_mode,
            "scheduled_at": (
                "2026-09-20T10:00:00+05:00"
                if execution_mode == "autonomous"
                else None
            ),
            "steps": [
                {
                    "step_id": "step-1",
                    "tool": "task",
                    "action": "create",
                    "data": {
                        "task": "Practice NOVA",
                    },
                    "depends_on": [],
                }
            ],
        },
        "reason": "Run this workflow?",
        "status": "processing",
        "created_at": datetime(
            2026,
            9,
            19,
            9,
            0,
        ),
        "expires_at": datetime(
            2026,
            9,
            19,
            9,
            5,
        ),
        "resolved_at": None,
    }


def test_single_tool_confirmation_executes_exact_saved_payload():
    tool_router = FakeToolRouter()

    service, confirmation_service = _build_service(
        claimed=_confirmed_tool(),
        finished={
            **_confirmed_tool(),
            "status": "consumed",
        },
        tool_router=tool_router,
    )

    result = service.execute_approved_confirmation(
        user_id="user-001",
        confirmation_id=101,
    )

    assert result.success is True
    assert result.status == "completed"
    assert result.confirmation["status"] == "consumed"

    assert tool_router.calls == [
        {
            "intent": "task",
            "user_id": "user-001",
            "data": {
                "task": "Practice NOVA",
            },
        }
    ]

    assert confirmation_service.finish_calls == [
        {
            "user_id": "user-001",
            "confirmation_id": 101,
            "success": True,
        }
    ]


def test_failed_tool_execution_finalizes_confirmation_as_failed():
    tool_router = FakeToolRouter(
        result={
            "success": False,
            "tool": "task",
            "action": "create",
            "result": None,
            "error": "Task creation failed.",
        }
    )

    service, confirmation_service = _build_service(
        claimed=_confirmed_tool(),
        finished={
            **_confirmed_tool(),
            "status": "failed",
        },
        tool_router=tool_router,
    )

    result = service.execute_approved_confirmation(
        user_id="user-001",
        confirmation_id=101,
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == "Task creation failed."

    assert confirmation_service.finish_calls[-1][
        "success"
    ] is False


def test_tool_exception_is_converted_to_failed_execution():
    tool_router = FakeToolRouter(
        raises=True
    )

    service, confirmation_service = _build_service(
        claimed=_confirmed_tool(),
        finished={
            **_confirmed_tool(),
            "status": "failed",
        },
        tool_router=tool_router,
    )

    result = service.execute_approved_confirmation(
        user_id="user-001",
        confirmation_id=101,
    )

    assert result.success is False
    assert result.status == "failed"

    assert result.tool_result["error"] == (
        "Tool execution failed."
    )

    assert confirmation_service.finish_calls[-1][
        "success"
    ] is False


def test_unavailable_confirmation_is_not_executed():
    service, confirmation_service = _build_service(
        claimed=None
    )

    result = service.execute_approved_confirmation(
        user_id="user-001",
        confirmation_id=999,
    )

    assert result.success is False
    assert result.status == "unavailable"
    assert result.confirmation is None
    assert result.error == (
        "This confirmation is no longer "
        "available for execution."
    )

    assert confirmation_service.finish_calls == []


def test_invalid_saved_confirmation_data_fails_safely():
    claimed = _confirmed_tool(
        data=None
    )
    claimed["data"] = "not-a-dictionary"

    service, confirmation_service = _build_service(
        claimed=claimed,
        finished={
            **claimed,
            "status": "failed",
        },
    )

    result = service.execute_approved_confirmation(
        user_id="user-001",
        confirmation_id=101,
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == (
        "The saved confirmation data is invalid."
    )

    assert confirmation_service.finish_calls[-1][
        "success"
    ] is False


def test_immediate_workflow_executes_persisted_steps():
    plan_service = FakePlanExecutionService()

    service, confirmation_service = _build_service(
        claimed=_confirmed_workflow(),
        finished={
            **_confirmed_workflow(),
            "status": "consumed",
        },
        plan_execution_service=plan_service,
    )

    result = service.execute_approved_confirmation(
        user_id="user-001",
        confirmation_id=102,
    )

    assert result.success is True
    assert result.status == "completed"
    assert result.confirmation["status"] == "consumed"

    assert plan_service.calls == [
        {
            "user_id": "user-001",
            "steps": [
                {
                    "step_id": "step-1",
                    "tool": "task",
                    "action": "create",
                    "data": {
                        "task": "Practice NOVA",
                    },
                    "depends_on": [],
                }
            ],
        }
    ]

    assert confirmation_service.finish_calls[-1][
        "success"
    ] is True


def test_scheduled_workflow_is_persisted_not_executed_now():
    workflow_service = FakeAutonomousWorkflowService()

    plan_service = FakePlanExecutionService()

    service, confirmation_service = _build_service(
        claimed=_confirmed_workflow(
            execution_mode="autonomous"
        ),
        finished={
            **_confirmed_workflow(
                execution_mode="autonomous"
            ),
            "status": "consumed",
        },
        plan_execution_service=plan_service,
        autonomous_workflow_service=workflow_service,
    )

    result = service.execute_approved_confirmation(
        user_id="user-001",
        confirmation_id=102,
    )

    assert result.success is True
    assert result.status == "scheduled"
    assert result.workflow_result["workflow_id"] == 88
    assert result.confirmation["status"] == "consumed"

    assert len(
        workflow_service.calls
    ) == 1

    assert (
        workflow_service.calls[0]["user_id"]
        == "user-001"
    )

    assert (
        workflow_service.calls[0][
            "idempotency_key"
        ]
        == "confirmation:102"
    )

    assert plan_service.calls == []

    assert confirmation_service.finish_calls[-1][
        "success"
    ] is True


def test_scheduled_workflow_failure_marks_confirmation_failed():
    workflow_service = FakeAutonomousWorkflowService(
        raises=True
    )

    service, confirmation_service = _build_service(
        claimed=_confirmed_workflow(
            execution_mode="autonomous"
        ),
        finished={
            **_confirmed_workflow(
                execution_mode="autonomous"
            ),
            "status": "failed",
        },
        autonomous_workflow_service=workflow_service,
    )

    result = service.execute_approved_confirmation(
        user_id="user-001",
        confirmation_id=102,
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == (
        "simulated schedule failure"
    )

    assert confirmation_service.finish_calls[-1][
        "success"
    ] is False


def test_workflow_execution_exception_finalizes_confirmation():
    class RaisingPlanExecutionService:
        def execute(
            self,
            *,
            user_id,
            steps,
        ):
            raise RuntimeError(
                "simulated workflow failure"
            )

    service, confirmation_service = _build_service(
        claimed=_confirmed_workflow(),
        finished={
            **_confirmed_workflow(),
            "status": "failed",
        },
        plan_execution_service=(
            RaisingPlanExecutionService()
        ),
    )

    result = service.execute_approved_confirmation(
        user_id="user-001",
        confirmation_id=102,
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == (
        "Workflow execution failed."
    )

    assert confirmation_service.finish_calls[-1][
        "success"
    ] is False


def test_confirmation_execution_uses_authenticated_user_id():
    tool_router = FakeToolRouter()

    service, confirmation_service = _build_service(
        claimed=_confirmed_tool(),
        finished={
            **_confirmed_tool(),
            "status": "consumed",
        },
        tool_router=tool_router,
    )

    result = service.execute_approved_confirmation(
        user_id="authenticated-user",
        confirmation_id=101,
    )

    assert result.success is True

    assert confirmation_service.claim_calls == [
        {
            "user_id": "authenticated-user",
            "confirmation_id": 101,
        }
    ]

    assert tool_router.calls[0][
        "user_id"
    ] == "authenticated-user"

def test_approve_and_execute_uses_atomic_confirmation_boundary():
    tool_router = FakeToolRouter()

    service, confirmation_service = _build_service(
        claimed=_confirmed_tool(),
        finished={
            **_confirmed_tool(),
            "status": "consumed",
        },
        tool_router=tool_router,
    )

    result = (
        service.approve_and_execute_confirmation(
            user_id="user-001",
            confirmation_id=101,
        )
    )

    assert result.success is True
    assert result.status == "completed"
    assert result.confirmation["status"] == "consumed"

    assert confirmation_service.approve_and_claim_calls == [
        {
            "user_id": "user-001",
            "confirmation_id": 101,
        }
    ]

    assert confirmation_service.claim_calls == []

    assert tool_router.calls == [
        {
            "intent": "task",
            "user_id": "user-001",
            "data": {
                "task": "Practice NOVA",
            },
        }
    ]


def test_approve_and_execute_does_not_execute_unavailable_confirmation():
    service, confirmation_service = _build_service(
        claimed=None
    )

    result = (
        service.approve_and_execute_confirmation(
            user_id="user-001",
            confirmation_id=999,
        )
    )

    assert result.success is False
    assert result.status == "unavailable"
    assert result.confirmation is None

    assert confirmation_service.approve_and_claim_calls == [
        {
            "user_id": "user-001",
            "confirmation_id": 999,
        }
    ]

    assert confirmation_service.finish_calls == []
