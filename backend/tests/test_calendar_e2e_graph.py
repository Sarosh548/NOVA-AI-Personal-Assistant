from __future__ import annotations

from types import SimpleNamespace

from agent import graph
from services.execution_context import (
    ExecutionContext,
)


def make_state(
    message: str,
) -> dict:
    return {
        "user_id": "user-001",
        "conversation_id": None,
        "user_message": message,
        "history": [],
        "understanding": {},
        "plan": {},
        "permission": {},
        "user_requested": True,
        "execution_context": ExecutionContext.interactive(),
        "confirmation": {},
        "tool_result": {},
        "workflow_result": {},
        "memory_context": "",
        "response": "",
    }


def patch_common_graph_dependencies(
    monkeypatch,
):
    monkeypatch.setattr(
        graph.confirmation_service,
        "parse_response",
        lambda message: None,
    )
    monkeypatch.setattr(
        graph.confirmation_service,
        "get_latest_pending_confirmation",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        graph.memory_service,
        "find_similar_memories",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        graph.memory_service,
        "get_profile_memories",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        graph.llm_service,
        "generate_response",
        lambda _prompt: "Calendar request completed.",
    )


def test_calendar_read_only_request_flows_through_full_graph(
    monkeypatch,
):
    patch_common_graph_dependencies(
        monkeypatch
    )

    captured = {}

    monkeypatch.setattr(
        graph.intent_service,
        "analyze",
        lambda message, history: {
            "intent": "calendar",
            "calendar_action": "list",
            "calendar_id": None,
            "event_id": None,
            "event": None,
            "time_min": "2026-09-21T00:00:00+05:00",
            "time_max": "2026-09-22T00:00:00+05:00",
            "query": None,
            "max_results": 20,
            "page_token": None,
            "single_events": True,
            "order_by": "startTime",
            "show_deleted": False,
            "send_updates": None,
            "requires_tool": True,
        },
    )

    def fake_permission_check(
        *,
        user_id,
        tool,
        action,
        user_requested,
        data,
    ):
        captured["permission"] = {
            "user_id": user_id,
            "tool": tool,
            "action": action,
            "user_requested": user_requested,
            "data": data,
        }

        return SimpleNamespace(
            allowed=True,
            requires_confirmation=False,
            reason="Read-only Calendar action is allowed.",
        )

    monkeypatch.setattr(
        graph.permission_service,
        "check",
        fake_permission_check,
    )

    def fake_tool_execute(
        *,
        intent,
        user_id,
        data,
    ):
        captured["tool"] = {
            "intent": intent,
            "user_id": user_id,
            "data": data,
        }

        return {
            "success": True,
            "tool": "calendar",
            "action": "list",
            "result": {
                "events": [
                    {
                        "event_id": "event-001",
                    }
                ]
            },
            "error": None,
        }

    monkeypatch.setattr(
        graph.tool_router,
        "execute",
        fake_tool_execute,
    )

    app = graph.build_graph()

    result = app.invoke(
        make_state(
            "What's on my calendar tomorrow?"
        )
    )

    assert result["understanding"]["intent"] == "calendar"
    assert result["plan"]["tool"] == "calendar"
    assert result["plan"]["action"] == "list"
    assert result["permission"]["allowed"] is True

    assert captured["permission"]["tool"] == "calendar"
    assert captured["permission"]["action"] == "list"
    assert captured["permission"]["user_requested"] is True

    assert captured["tool"]["intent"] == "calendar"
    assert captured["tool"]["user_id"] == "user-001"
    assert captured["tool"]["data"]["calendar_action"] == "list"
    assert (
        captured["tool"]["data"]["time_min"]
        == "2026-09-21T00:00:00+05:00"
    )

    assert result["tool_result"]["success"] is True
    assert result["tool_result"]["tool"] == "calendar"
    assert result["response"] == "Calendar request completed."


def test_calendar_create_invitation_requires_confirmation_and_approval_executes_saved_action(
    monkeypatch,
):
    patch_common_graph_dependencies(
        monkeypatch
    )

    pending = {}
    captured = {
        "tool_calls": [],
        "approved_confirmation_ids": [],
    }

    create_data = {
        "calendar_action": "create",
        "calendar_id": "primary",
        "event": {
            "summary": "Client meeting",
            "start": {
                "dateTime": (
                    "2026-09-21T16:00:00+05:00"
                )
            },
            "end": {
                "dateTime": (
                    "2026-09-21T17:00:00+05:00"
                )
            },
            "attendees": [
                {
                    "email": "client@example.com",
                }
            ],
        },
        "send_updates": "all",
    }

    monkeypatch.setattr(
        graph.intent_service,
        "analyze",
        lambda message, history: {
            "intent": "calendar",
            "calendar_action": "create",
            "calendar_id": "primary",
            "event_id": None,
            "event": {
                "summary": "Client meeting",
                "start": {
                    "dateTime": (
                        "2026-09-21T16:00:00+05:00"
                    )
                },
                "end": {
                    "dateTime": (
                        "2026-09-21T17:00:00+05:00"
                    )
                },
                "attendees": [
                    {
                        "email": "client@example.com",
                    }
                ],
            },
            "time_min": None,
            "time_max": None,
            "query": None,
            "max_results": None,
            "page_token": None,
            "single_events": None,
            "order_by": None,
            "show_deleted": None,
            "send_updates": "all",
            "requires_tool": True,
        }
        if "approve" not in message.lower()
        else {
            "intent": "chat",
            "requires_tool": False,
        },
    )

    monkeypatch.setattr(
        graph.confirmation_service,
        "parse_response",
        lambda message: (
            "approve"
            if message.strip().lower() == "approve"
            else None
        ),
    )

    def fake_get_pending(
        *,
        user_id,
        conversation_id,
    ):
        return (
            dict(pending)
            if pending.get("status") == "pending"
            else None
        )

    monkeypatch.setattr(
        graph.confirmation_service,
        "get_latest_pending_confirmation",
        fake_get_pending,
    )

    def fake_create_confirmation(
        *,
        user_id,
        conversation_id,
        tool,
        action,
        data,
        reason,
    ):
        pending.update(
            {
                "id": "confirmation-001",
                "user_id": user_id,
                "conversation_id": conversation_id,
                "tool": tool,
                "action": action,
                "data": dict(data),
                "reason": reason,
                "status": "pending",
            }
        )
        return "confirmation-001"

    monkeypatch.setattr(
        graph.confirmation_service,
        "create_confirmation",
        fake_create_confirmation,
    )

    def fake_approve_confirmation(
        *,
        user_id,
        confirmation_id,
    ):
        if (
            pending.get("id") != confirmation_id
            or pending.get("status") != "pending"
        ):
            return None

        pending["status"] = "approved"

        return dict(pending)

    monkeypatch.setattr(
        graph.confirmation_service,
        "approve_confirmation",
        fake_approve_confirmation,
    )

    monkeypatch.setattr(
        graph.permission_service,
        "check",
        lambda **_kwargs: SimpleNamespace(
            allowed=False,
            requires_confirmation=True,
            reason=(
                "High-risk action requires explicit confirmation."
            ),
        ),
    )

    def fake_approved_execution(
        *,
        user_id,
        confirmation_id,
    ):
        captured["approved_confirmation_ids"].append(
            confirmation_id
        )

        return SimpleNamespace(
            success=True,
            status="consumed",
            error=None,
            confirmation={
                "id": "confirmation-001",
                "status": "consumed",
                "tool": "calendar",
                "action": "create",
                "reason": pending["reason"],
            },
            tool_result={
                "success": True,
                "tool": "calendar",
                "action": "create",
                "result": {
                    "event_id": "event-001",
                },
                "error": None,
            },
            workflow_result={},
        )

    monkeypatch.setattr(
        graph.confirmation_execution_service,
        "execute_approved_confirmation",
        fake_approved_execution,
    )

    def fake_tool_execute(**kwargs):
        captured["tool_calls"].append(
            kwargs
        )
        return {
            "success": True,
            "tool": "calendar",
            "action": "create",
            "result": {
                "event_id": "should-not-be-used",
            },
            "error": None,
        }

    monkeypatch.setattr(
        graph.tool_router,
        "execute",
        fake_tool_execute,
    )

    app = graph.build_graph()

    first_result = app.invoke(
        make_state(
            "Create a client meeting tomorrow at 4 PM "
            "and invite client@example.com."
        )
    )

    assert (
        first_result["permission"]["requires_confirmation"]
        is True
    )
    assert first_result["permission"]["allowed"] is False
    assert (
        first_result["confirmation"]["status"]
        == "pending"
    )
    assert first_result["confirmation"]["tool"] == "calendar"
    assert first_result["confirmation"]["action"] == "create"
    assert first_result["tool_result"]["success"] is False
    assert captured["tool_calls"] == []
    assert pending["data"] == (
        first_result["plan"]["data"]
    )

    second_state = make_state(
        "approve"
    )
    second_state["conversation_id"] = None

    second_result = app.invoke(
        second_state
    )

    assert captured["approved_confirmation_ids"] == [
        "confirmation-001"
    ]
    assert captured["tool_calls"] == []
    assert second_result["confirmation"]["status"] == "consumed"
    assert second_result["tool_result"]["success"] is True
    assert second_result["tool_result"]["action"] == "create"
    assert (
        second_result["tool_result"]["result"]["event_id"]
        == "event-001"
    )
