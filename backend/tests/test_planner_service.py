from services.planner_service import PlannerService


def test_planner_returns_non_tool_plan_for_normal_chat():
    planner = PlannerService()

    understanding = {
        "intent": "chat",
        "requires_tool": False,
    }

    available_tools = [
        {
            "name": "task",
            "description": "Manage tasks.",
            "actions": [
                "create",
                "complete",
            ],
        }
    ]

    plan = planner.create_plan(
        understanding=understanding,
        available_tools=available_tools,
    )

    assert plan.requires_tool is False
    assert plan.tool is None
    assert plan.action is None


def test_planner_creates_task_plan():
    planner = PlannerService()

    understanding = {
        "intent": "task",
        "requires_tool": True,
        "task_action": "create",
        "task": "Practice Python",
        "priority": "high",
    }

    available_tools = [
        {
            "name": "task",
            "description": "Manage tasks.",
            "actions": [
                "create",
                "list",
                "start",
                "complete",
                "cancel",
                "delete",
                "update",
            ],
        }
    ]

    plan = planner.create_plan(
        understanding=understanding,
        available_tools=available_tools,
    )

    assert plan.requires_tool is True
    assert plan.tool == "task"
    assert plan.action == "create"
    assert plan.data["task_action"] == "create"
    assert plan.data["tool"] == "task"
    assert plan.data["action"] == "create"


def test_planner_creates_reminder_plan():
    planner = PlannerService()

    understanding = {
        "intent": "reminder",
        "requires_tool": True,
        "reminder_action": "create",
        "task": "Call HR",
        "scheduled_at": "2026-09-17T10:00:00+05:00",
    }

    available_tools = [
        {
            "name": "reminder",
            "description": "Manage reminders.",
            "actions": [
                "create",
                "list",
                "complete",
                "cancel",
                "delete",
                "update",
            ],
        }
    ]

    plan = planner.create_plan(
        understanding=understanding,
        available_tools=available_tools,
    )

    assert plan.requires_tool is True
    assert plan.tool == "reminder"
    assert plan.action == "create"
    assert plan.data["reminder_action"] == "create"
    assert plan.data["tool"] == "reminder"
    assert plan.data["action"] == "create"


def test_planner_rejects_unavailable_tool():
    planner = PlannerService()

    understanding = {
        "intent": "calendar",
        "requires_tool": True,
        "action": "list",
    }

    available_tools = [
        {
            "name": "task",
            "description": "Manage tasks.",
            "actions": ["create", "list"],
        }
    ]

    plan = planner.create_plan(
        understanding=understanding,
        available_tools=available_tools,
    )

    assert plan.requires_tool is False
    assert plan.tool is None
    assert plan.action is None
    assert "not currently available" in plan.reason


def test_planner_rejects_unsupported_action():
    planner = PlannerService()

    understanding = {
        "intent": "task",
        "requires_tool": True,
        "task_action": "send_email",
    }

    available_tools = [
        {
            "name": "task",
            "description": "Manage tasks.",
            "actions": [
                "create",
                "list",
                "complete",
            ],
        }
    ]

    plan = planner.create_plan(
        understanding=understanding,
        available_tools=available_tools,
    )

    assert plan.requires_tool is False
    assert plan.tool is None
    assert plan.action is None
    assert "No valid action" in plan.reason


def test_planner_does_not_execute_any_tool():
    planner = PlannerService()

    understanding = {
        "intent": "task",
        "requires_tool": True,
        "task_action": "complete",
        "task_reference": "Docker task",
    }

    available_tools = [
        {
            "name": "task",
            "description": "Manage tasks.",
            "actions": [
                "complete",
            ],
        }
    ]

    plan = planner.create_plan(
        understanding=understanding,
        available_tools=available_tools,
    )

    assert plan.requires_tool is True
    assert plan.tool == "task"
    assert plan.action == "complete"

    # Planner only creates a decision.
    # It must never contain an execution result.
    assert "tool_result" not in plan.data