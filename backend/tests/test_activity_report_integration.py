from agent import graph
from agent.graph import (
    activity_report_node,
    route_after_understanding_activity_report,
    understanding_node,
)


def test_understanding_node_detects_daily_activity_report_without_llm(
    monkeypatch,
):
    def fail_if_called(
        message,
        history,
    ):
        raise AssertionError(
            "IntentService should not be called "
            "for a deterministic activity-report request."
        )

    monkeypatch.setattr(
        graph.intent_service,
        "analyze",
        fail_if_called,
    )

    state = {
        "user_id": "user-001",
        "conversation_id": None,
        "user_message": "Aaj kya updates hain?",
        "history": [],
        "understanding": {},
        "plan": {},
        "permission": {
            "allowed": False,
            "requires_confirmation": False,
            "reason": "",
        },
        "user_requested": True,
        "confirmation": {
            "id": None,
            "status": None,
            "tool": None,
            "action": None,
            "reason": None,
        },
        "tool_result": {
            "success": False,
            "tool": None,
            "action": None,
            "result": None,
            "error": None,
        },
        "workflow_result": {
            "success": False,
            "status": None,
            "steps": [],
            "error": None,
        },
        "memory_context": "",
        "response": "",
    }

    result = understanding_node(
        state
    )

    assert (
        result["understanding"]["intent"]
        == "activity_report"
    )

    assert (
        result["understanding"]["requires_tool"]
        is False
    )


def test_activity_report_request_routes_directly_to_report_node():
    state = {
        "understanding": {
            "intent": "activity_report",
            "requires_tool": False,
        }
    }

    route = (
        route_after_understanding_activity_report(
            state
        )
    )

    assert route == "activity_report"


def test_normal_request_routes_to_planner():
    state = {
        "understanding": {
            "intent": "chat",
            "requires_tool": False,
        }
    }

    route = (
        route_after_understanding_activity_report(
            state
        )
    )

    assert route == "planner"


def test_activity_report_node_uses_user_scoped_report_service(
    monkeypatch,
):
    calls = []

    class FakeActivityReportService:
        def get_daily_report(
            self,
            *,
            user_id,
        ):
            calls.append(
                user_id
            )

            return {
                "user_id": user_id,
                "timezone": "Asia/Karachi",
                "total_events": 3,
                "status_counts": {
                    "success": 2,
                    "pending": 1,
                },
                "event_type_counts": {
                    "workflow_completed": 2,
                    "workflow_scheduled": 1,
                },
                "successful_count": 2,
                "pending_count": 1,
                "partial_count": 0,
                "failed_count": 0,
                "blocked_count": 0,
                "recent_events": [],
                "report_text": (
                    "Aaj 3 activities hui hain."
                ),
            }

    monkeypatch.setattr(
        graph,
        "activity_report_service",
        FakeActivityReportService(),
    )

    state = {
        "user_id": "user-001",
        "conversation_id": 55,
        "user_message": "Aaj kya updates hain?",
        "history": [],
        "understanding": {
            "intent": "activity_report",
            "requires_tool": False,
        },
        "plan": {},
        "permission": {},
        "user_requested": True,
        "confirmation": {},
        "tool_result": {},
        "workflow_result": {},
        "memory_context": "",
        "response": "",
    }

    result = activity_report_node(
        state
    )

    assert calls == [
        "user-001"
    ]

    assert (
        result["activity_report"][
            "total_events"
        ]
        == 3
    )

    assert (
        result["activity_report"][
            "successful_count"
        ]
        == 2
    )

    assert (
        result["activity_report"][
            "pending_count"
        ]
        == 1
    )

    assert (
        result["activity_report"][
            "report_text"
        ]
        == "Aaj 3 activities hui hain."
    )


def test_activity_report_node_fails_safely(
    monkeypatch,
):
    class FailingActivityReportService:
        def get_daily_report(
            self,
            *,
            user_id,
        ):
            raise RuntimeError(
                "database unavailable"
            )

    monkeypatch.setattr(
        graph,
        "activity_report_service",
        FailingActivityReportService(),
    )

    state = {
        "user_id": "user-001",
        "conversation_id": None,
        "user_message": "Aaj ki activity",
        "history": [],
        "understanding": {
            "intent": "activity_report",
            "requires_tool": False,
        },
        "plan": {},
        "permission": {},
        "user_requested": True,
        "confirmation": {},
        "tool_result": {},
        "workflow_result": {},
        "memory_context": "",
        "response": "",
    }

    result = activity_report_node(
        state
    )

    report = result[
        "activity_report"
    ]

    assert report["user_id"] == "user-001"
    assert (
        report["error"]
        == (
            "The activity report could not "
            "be generated."
        )
    )