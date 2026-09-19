from agent import graph
from services.confirmation_execution_service import (
    ConfirmationExecutionResult,
)


class FakeConfirmationExecutionService:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute_approved_confirmation(
        self,
        *,
        user_id,
        confirmation_id,
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "confirmation_id": confirmation_id,
            }
        )
        return self.result


def _confirmation(
    *,
    status="consumed",
    tool="task",
    action="delete",
):
    return {
        "id": 41,
        "status": status,
        "tool": tool,
        "action": action,
        "reason": "Approved by the user.",
    }


def test_tool_node_delegates_approved_confirmation(
    monkeypatch,
):
    fake_service = FakeConfirmationExecutionService(
        ConfirmationExecutionResult(
            success=True,
            status="completed",
            confirmation=_confirmation(),
            tool_result={
                "success": True,
                "tool": "task",
                "action": "delete",
                "result": {"deleted": True},
                "error": None,
            },
            workflow_result={
                "success": False,
                "status": None,
                "workflow_id": None,
                "scheduled_at": None,
                "steps": [],
                "error": None,
            },
            error=None,
        )
    )

    monkeypatch.setattr(
        graph,
        "confirmation_execution_service",
        fake_service,
    )

    result = graph.tool_node(
        {
            "user_id": "test-user",
            "plan": {
                "requires_tool": True,
                "execution_mode": "single",
                "tool": "task",
                "action": "delete",
                "data": {
                    "task_id": 999,
                },
            },
            "permission": {
                "allowed": True,
                "requires_confirmation": False,
            },
            "confirmation": {
                "id": 41,
                "status": "approved",
                "tool": "task",
                "action": "delete",
                "reason": "Delete this task?",
            },
            "tool_result": {},
        }
    )

    assert fake_service.calls == [
        {
            "user_id": "test-user",
            "confirmation_id": 41,
        }
    ]

    assert result["confirmation"]["status"] == "consumed"
    assert result["tool_result"]["success"] is True
    assert result["tool_result"]["result"] == {
        "deleted": True
    }


def test_tool_node_surfaces_unavailable_confirmation(
    monkeypatch,
):
    fake_service = FakeConfirmationExecutionService(
        ConfirmationExecutionResult(
            success=False,
            status="unavailable",
            confirmation=None,
            tool_result={
                "success": False,
                "tool": None,
                "action": None,
                "result": None,
                "error": None,
            },
            workflow_result={
                "success": False,
                "status": None,
                "workflow_id": None,
                "scheduled_at": None,
                "steps": [],
                "error": None,
            },
            error=(
                "This confirmation is no longer "
                "available for execution."
            ),
        )
    )

    monkeypatch.setattr(
        graph,
        "confirmation_execution_service",
        fake_service,
    )

    result = graph.tool_node(
        {
            "user_id": "test-user",
            "plan": {
                "requires_tool": True,
                "execution_mode": "single",
                "tool": "task",
                "action": "delete",
                "data": {},
            },
            "permission": {
                "allowed": True,
                "requires_confirmation": False,
            },
            "confirmation": {
                "id": 41,
                "status": "approved",
                "tool": "task",
                "action": "delete",
                "reason": "Delete this task?",
            },
            "tool_result": {},
        }
    )

    assert fake_service.calls[0]["confirmation_id"] == 41
    assert result["tool_result"]["success"] is False
    assert result["tool_result"]["tool"] == "task"
    assert result["tool_result"]["action"] == "delete"
    assert result["tool_result"]["error"] == (
        "This confirmation is no longer "
        "available for execution."
    )


def test_workflow_node_delegates_approved_confirmation(
    monkeypatch,
):
    fake_service = FakeConfirmationExecutionService(
        ConfirmationExecutionResult(
            success=True,
            status="completed",
            confirmation=_confirmation(
                tool="workflow",
                action="execute",
            ),
            tool_result={
                "success": False,
                "tool": None,
                "action": None,
                "result": None,
                "error": None,
            },
            workflow_result={
                "success": True,
                "status": "completed",
                "workflow_id": None,
                "scheduled_at": None,
                "steps": [
                    {
                        "step_id": "step-1",
                        "tool": "task",
                        "action": "create",
                        "status": "completed",
                        "result": {
                            "id": 123,
                        },
                        "error": None,
                    }
                ],
                "error": None,
            },
            error=None,
        )
    )

    monkeypatch.setattr(
        graph,
        "confirmation_execution_service",
        fake_service,
    )

    result = graph.workflow_node(
        {
            "user_id": "test-user",
            "plan": {
                "requires_tool": True,
                "execution_mode": "workflow",
                "scheduled_at": None,
                "steps": [
                    {
                        "step_id": "step-1",
                        "tool": "task",
                        "action": "create",
                        "data": {
                            "task": "Wrong graph data",
                        },
                        "depends_on": [],
                    }
                ],
            },
            "permission": {
                "allowed": True,
                "requires_confirmation": False,
            },
            "confirmation": {
                "id": 41,
                "status": "approved",
                "tool": "workflow",
                "action": "execute",
                "reason": "Run this workflow?",
            },
            "workflow_result": {},
        }
    )

    assert fake_service.calls == [
        {
            "user_id": "test-user",
            "confirmation_id": 41,
        }
    ]

    assert result["confirmation"]["status"] == "consumed"
    assert result["workflow_result"]["success"] is True
    assert result["workflow_result"]["status"] == "completed"


def test_workflow_node_surfaces_unavailable_confirmation(
    monkeypatch,
):
    fake_service = FakeConfirmationExecutionService(
        ConfirmationExecutionResult(
            success=False,
            status="unavailable",
            confirmation=None,
            tool_result={
                "success": False,
                "tool": None,
                "action": None,
                "result": None,
                "error": None,
            },
            workflow_result={
                "success": False,
                "status": None,
                "workflow_id": None,
                "scheduled_at": None,
                "steps": [],
                "error": None,
            },
            error=(
                "This confirmation is no longer "
                "available for execution."
            ),
        )
    )

    monkeypatch.setattr(
        graph,
        "confirmation_execution_service",
        fake_service,
    )

    result = graph.workflow_node(
        {
            "user_id": "test-user",
            "plan": {
                "requires_tool": True,
                "execution_mode": "workflow",
                "scheduled_at": None,
                "steps": [],
            },
            "permission": {
                "allowed": True,
                "requires_confirmation": False,
            },
            "confirmation": {
                "id": 41,
                "status": "approved",
                "tool": "workflow",
                "action": "execute",
                "reason": "Run this workflow?",
            },
            "workflow_result": {},
        }
    )

    assert fake_service.calls[0]["confirmation_id"] == 41
    assert result["workflow_result"]["success"] is False
    assert result["workflow_result"]["status"] == "blocked"
    assert result["workflow_result"]["error"] == (
        "This confirmation is no longer "
        "available for execution."
    )


def test_workflow_node_routes_invalid_confirmed_payload_to_service(
    monkeypatch,
):
    fake_service = FakeConfirmationExecutionService(
        ConfirmationExecutionResult(
            success=False,
            status="failed",
            confirmation=_confirmation(
                status="failed",
                tool="workflow",
                action="execute",
            ),
            tool_result={
                "success": False,
                "tool": None,
                "action": None,
                "result": None,
                "error": None,
            },
            workflow_result={
                "success": False,
                "status": "failed",
                "workflow_id": None,
                "scheduled_at": None,
                "steps": [],
                "error": "The saved confirmation data is invalid.",
            },
            error="The saved confirmation data is invalid.",
        )
    )

    monkeypatch.setattr(
        graph,
        "confirmation_execution_service",
        fake_service,
    )

    result = graph.workflow_node(
        {
            "user_id": "test-user",
            "plan": {
                "requires_tool": True,
                "execution_mode": None,
                "scheduled_at": None,
                "steps": [],
            },
            "permission": {
                "allowed": True,
                "requires_confirmation": False,
            },
            "confirmation": {
                "id": 41,
                "status": "approved",
                "tool": "workflow",
                "action": "execute",
                "reason": "Run this workflow?",
            },
            "workflow_result": {},
        }
    )

    assert fake_service.calls[0]["confirmation_id"] == 41
    assert result["confirmation"]["status"] == "failed"
    assert result["workflow_result"]["status"] == "failed"
    assert result["workflow_result"]["error"] == (
        "The saved confirmation data is invalid."
    )