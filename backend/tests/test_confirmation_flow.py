from agent import graph
from services.confirmation_execution_service import (
    ConfirmationExecutionService,
)


class FakeConfirmationService:
    def __init__(
        self,
        pending=None,
        response_type=None,
    ):
        self.pending = pending
        self.response_type = response_type
        self.approved_ids = []
        self.rejected_ids = []
        self.claimed_ids = []
        self.finished_calls = []

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

    def approve_confirmation(
        self,
        user_id,
        confirmation_id,
    ):
        self.approved_ids.append(
            confirmation_id
        )

        pending = self.pending.copy()
        pending["status"] = "approved"

        return pending

    def reject_confirmation(
        self,
        user_id,
        confirmation_id,
    ):
        self.rejected_ids.append(
            confirmation_id
        )

        pending = self.pending.copy()
        pending["status"] = "rejected"

        return pending

    def claim_confirmation(
        self,
        user_id,
        confirmation_id,
    ):
        if confirmation_id in self.claimed_ids:
            return None

        self.claimed_ids.append(
            confirmation_id
        )

        pending = self.pending.copy()
        pending["status"] = "processing"

        return pending

    def finish_confirmation(
        self,
        user_id,
        confirmation_id,
        success,
    ):
        self.finished_calls.append(
            {
                "user_id": user_id,
                "confirmation_id": confirmation_id,
                "success": success,
            }
        )

        pending = self.pending.copy()

        pending["status"] = (
            "consumed"
            if success
            else "failed"
        )

        return pending


class FakeToolRouter:
    def __init__(self):
        self.executed_calls = []

    def execute(
        self,
        intent,
        user_id,
        data=None,
    ):
        self.executed_calls.append(
            {
                "intent": intent,
                "user_id": user_id,
                "data": data,
            }
        )

        return {
            "success": True,
            "tool": intent,
            "action": (
                data.get("task_action")
                or data.get("reminder_action")
                or data.get("action")
            ),
            "result": {
                "message": "approved execution succeeded",
            },
            "error": None,
        }


def _base_state():
    return {
        "user_id": "user-001",
        "conversation_id": 42,
        "user_message": "yes",
        "history": [],
        "understanding": {},
        "plan": {},
        "permission": {},
        "user_requested": True,
        "confirmation": {},
        "tool_result": {
            "success": False,
            "tool": None,
            "action": None,
            "result": None,
            "error": None,
        },
        "memory_context": "",
        "response": "",
    }


def test_approved_confirmation_rebuilds_exact_plan(
    monkeypatch,
):
    fake_confirmation = (
        FakeConfirmationService(
            pending={
                "id": 701,
                "status": "pending",
                "tool": "task",
                "action": "delete",
                "data": {
                    "task_action": "delete",
                    "task_reference": "Old task",
                },
                "reason": (
                    "Delete task requires confirmation."
                ),
            },
            response_type="approve",
        )
    )

    monkeypatch.setattr(
        graph,
        "confirmation_service",
        fake_confirmation,
    )

    state = _base_state()

    result = graph.confirmation_node(
        state
    )

    assert result["confirmation"]["id"] == 701
    assert (
        result["confirmation"]["status"]
        == "approved"
    )

    assert (
        result["permission"]["allowed"]
        is True
    )

    assert (
        result["permission"]
        ["requires_confirmation"]
        is False
    )

    assert (
        result["plan"]["requires_tool"]
        is True
    )

    assert (
        result["plan"]["tool"]
        == "task"
    )

    assert (
        result["plan"]["action"]
        == "delete"
    )

    assert (
        result["plan"]["data"]
        ["task_reference"]
        == "Old task"
    )

    assert fake_confirmation.approved_ids == [701]

    assert (
        graph.route_after_confirmation(
            result
        )
        == "tool"
    )


def test_approved_confirmation_executes_exact_saved_action_once(
    monkeypatch,
):
    fake_confirmation = (
        FakeConfirmationService(
            pending={
                "id": 702,
                "status": "pending",
                "tool": "task",
                "action": "complete",
                "data": {
                    "task_action": "complete",
                    "task_id": 13,
                },
                "reason": (
                    "Complete task requires confirmation."
                ),
            },
            response_type="approve",
        )
    )

    fake_router = FakeToolRouter()

    monkeypatch.setattr(
        graph,
        "confirmation_service",
        fake_confirmation,
    )

    monkeypatch.setattr(
        graph,
        "tool_router",
        fake_router,
    )

    execution_service = ConfirmationExecutionService(
        confirmation_service=fake_confirmation,
        tool_router=fake_router,
    )

    monkeypatch.setattr(
        graph,
        "confirmation_execution_service",
        execution_service,
    )

    state = _base_state()

    confirmed = graph.confirmation_node(
        state
    )

    assert (
        graph.route_after_confirmation(
            confirmed
        )
        == "tool"
    )

    executed = graph.tool_node(
        confirmed
    )

    assert (
        executed["tool_result"]
        ["success"]
        is True
    )

    assert (
        executed["confirmation"]
        ["status"]
        == "consumed"
    )

    assert (
        len(fake_router.executed_calls)
        == 1
    )

    call = fake_router.executed_calls[0]

    assert call["intent"] == "task"
    assert call["user_id"] == "user-001"
    assert (
        call["data"]["task_action"]
        == "complete"
    )
    assert (
        call["data"]["task_id"]
        == 13
    )

    assert fake_confirmation.claimed_ids == [702]

    assert (
        fake_confirmation.finished_calls
        == [
            {
                "user_id": "user-001",
                "confirmation_id": 702,
                "success": True,
            }
        ]
    )


def test_replayed_confirmation_cannot_execute_again(
    monkeypatch,
):
    fake_confirmation = (
        FakeConfirmationService(
            pending={
                "id": 703,
                "status": "pending",
                "tool": "task",
                "action": "delete",
                "data": {
                    "task_action": "delete",
                    "task_id": 20,
                },
                "reason": (
                    "Delete task requires confirmation."
                ),
            },
            response_type="approve",
        )
    )

    fake_router = FakeToolRouter()

    monkeypatch.setattr(
        graph,
        "confirmation_service",
        fake_confirmation,
    )

    monkeypatch.setattr(
        graph,
        "tool_router",
        fake_router,
    )

    execution_service = ConfirmationExecutionService(
        confirmation_service=fake_confirmation,
        tool_router=fake_router,
    )

    monkeypatch.setattr(
        graph,
        "confirmation_execution_service",
        execution_service,
    )

    state = _base_state()

    confirmed = graph.confirmation_node(
        state
    )

    first = graph.tool_node(
        confirmed
    )

    assert (
        first["tool_result"]["success"]
        is True
    )

    second = graph.tool_node(
        confirmed
    )

    assert (
        second["tool_result"]["success"]
        is False
    )

    assert (
        "no longer available"
        in second["tool_result"]["error"]
    )

    assert (
        len(fake_router.executed_calls)
        == 1
    )


def test_rejected_confirmation_never_reaches_tool(
    monkeypatch,
):
    fake_confirmation = (
        FakeConfirmationService(
            pending={
                "id": 704,
                "status": "pending",
                "tool": "task",
                "action": "delete",
                "data": {
                    "task_action": "delete",
                    "task_id": 20,
                },
                "reason": (
                    "Delete task requires confirmation."
                ),
            },
            response_type="reject",
        )
    )

    fake_router = FakeToolRouter()

    monkeypatch.setattr(
        graph,
        "confirmation_service",
        fake_confirmation,
    )

    monkeypatch.setattr(
        graph,
        "tool_router",
        fake_router,
    )

    state = _base_state()
    state["user_message"] = "no"

    result = graph.confirmation_node(
        state
    )

    assert (
        result["confirmation"]["status"]
        == "rejected"
    )

    assert (
        result["permission"]["allowed"]
        is False
    )

    assert (
        graph.route_after_confirmation(
            result
        )
        == "agent"
    )

    executed = graph.tool_node(
        result
    )

    assert (
        executed["tool_result"]["success"]
        is False
    )

    assert fake_router.executed_calls == []
    assert fake_confirmation.rejected_ids == [704]


def test_no_pending_confirmation_continues_normal_flow(
    monkeypatch,
):
    fake_confirmation = (
        FakeConfirmationService(
            pending=None,
            response_type="approve",
        )
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
        result["confirmation"]["id"]
        is None
    )

    assert (
        graph.route_after_confirmation(
            result
        )
        == "memory"
    )


def test_ambiguous_message_does_not_approve_pending_action(
    monkeypatch,
):
    fake_confirmation = (
        FakeConfirmationService(
            pending={
                "id": 705,
                "status": "pending",
                "tool": "task",
                "action": "delete",
                "data": {
                    "task_action": "delete",
                    "task_id": 21,
                },
                "reason": (
                    "Delete task requires confirmation."
                ),
            },
            response_type=None,
        )
    )

    monkeypatch.setattr(
        graph,
        "confirmation_service",
        fake_confirmation,
    )

    state = _base_state()

    state["user_message"] = (
        "Tell me more about this."
    )

    result = graph.confirmation_node(
        state
    )

    assert (
        result["confirmation"]["id"]
        == 705
    )

    assert (
        result["confirmation"]["status"]
        == "pending"
    )

    assert (
        graph.route_after_confirmation(
            result
        )
        == "memory"
    )

    assert fake_confirmation.approved_ids == []
    assert fake_confirmation.rejected_ids == []