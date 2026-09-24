import pytest

from services.planner_service import (
    PlanStep,
    PlannerService,
)


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
    assert plan.steps == ()


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

    assert len(plan.steps) == 1

    step = plan.steps[0]

    assert isinstance(step, PlanStep)
    assert step.step_id == "step-1"
    assert step.tool == "task"
    assert step.action == "create"
    assert step.data["task"] == "Practice Python"
    assert step.data["task_action"] == "create"
    assert step.depends_on == ()


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

    assert len(plan.steps) == 1

    step = plan.steps[0]

    assert step.step_id == "step-1"
    assert step.tool == "reminder"
    assert step.action == "create"
    assert step.data["task"] == "Call HR"
    assert step.data["reminder_action"] == "create"
    assert step.depends_on == ()


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
    assert plan.steps == ()
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
    assert plan.steps == ()
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

    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "task"
    assert plan.steps[0].action == "complete"

    assert "tool_result" not in plan.data
    assert "tool_result" not in plan.steps[0].data


def test_plan_step_supports_dependencies():
    step = PlanStep(
        step_id="step-2",
        tool="task",
        action="complete",
        data={
            "task_action": "complete",
            "task_id": 13,
        },
        depends_on=("step-1",),
    )

    assert step.step_id == "step-2"
    assert step.tool == "task"
    assert step.action == "complete"
    assert step.data["task_id"] == 13
    assert step.depends_on == ("step-1",)


def test_planner_creates_valid_multi_step_plan():
    planner = PlannerService()

    available_tools = [
        {
            "name": "task",
            "description": "Manage tasks.",
            "actions": [
                "create",
                "list",
                "complete",
            ],
        },
        {
            "name": "reminder",
            "description": "Manage reminders.",
            "actions": [
                "create",
                "list",
            ],
        },
    ]

    plan = planner.create_multi_step_plan(
        steps=[
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
                    "task": "Review task list",
                    "scheduled_at": (
                        "2026-09-18T10:00:00+05:00"
                    ),
                },
                "depends_on": ["step-1"],
            },
        ],
        available_tools=available_tools,
    )

    assert plan.requires_tool is True
    assert plan.tool is None
    assert plan.action is None
    assert len(plan.steps) == 2

    first = plan.steps[0]
    second = plan.steps[1]

    assert first.step_id == "step-1"
    assert first.tool == "task"
    assert first.action == "list"
    assert first.depends_on == ()

    assert second.step_id == "step-2"
    assert second.tool == "reminder"
    assert second.action == "create"
    assert second.depends_on == ("step-1",)

    assert (
        plan.data["steps"][1]["depends_on"]
        == ["step-1"]
    )


def test_planner_rejects_duplicate_multi_step_ids():
    planner = PlannerService()

    available_tools = [
        {
            "name": "task",
            "description": "Manage tasks.",
            "actions": ["list"],
        }
    ]

    plan = planner.create_multi_step_plan(
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "list",
                "data": {},
                "depends_on": [],
            },
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "list",
                "data": {},
                "depends_on": [],
            },
        ],
        available_tools=available_tools,
    )

    assert plan.requires_tool is False
    assert plan.steps == ()
    assert "Duplicate plan step ID" in plan.reason


def test_planner_rejects_unknown_multi_step_dependency():
    planner = PlannerService()

    available_tools = [
        {
            "name": "task",
            "description": "Manage tasks.",
            "actions": ["list"],
        }
    ]

    plan = planner.create_multi_step_plan(
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "list",
                "data": {},
                "depends_on": ["missing-step"],
            }
        ],
        available_tools=available_tools,
    )

    assert plan.requires_tool is False
    assert plan.steps == ()
    assert "depends on unknown step" in plan.reason


def test_planner_rejects_multi_step_self_dependency():
    planner = PlannerService()

    available_tools = [
        {
            "name": "task",
            "description": "Manage tasks.",
            "actions": ["list"],
        }
    ]

    plan = planner.create_multi_step_plan(
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "list",
                "data": {},
                "depends_on": ["step-1"],
            }
        ],
        available_tools=available_tools,
    )

    assert plan.requires_tool is False
    assert plan.steps == ()
    assert "cannot depend on itself" in plan.reason


def test_planner_rejects_multi_step_dependency_cycle():
    planner = PlannerService()

    available_tools = [
        {
            "name": "task",
            "description": "Manage tasks.",
            "actions": ["list"],
        }
    ]

    plan = planner.create_multi_step_plan(
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "list",
                "data": {},
                "depends_on": ["step-2"],
            },
            {
                "step_id": "step-2",
                "tool": "task",
                "action": "list",
                "data": {},
                "depends_on": ["step-1"],
            },
        ],
        available_tools=available_tools,
    )

    assert plan.requires_tool is False
    assert plan.steps == ()
    assert "dependency cycle" in plan.reason


def test_planner_rejects_unsupported_multi_step_action():
    planner = PlannerService()

    available_tools = [
        {
            "name": "task",
            "description": "Manage tasks.",
            "actions": ["list"],
        }
    ]

    plan = planner.create_multi_step_plan(
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "delete",
                "data": {},
                "depends_on": [],
            }
        ],
        available_tools=available_tools,
    )

    assert plan.requires_tool is False
    assert plan.steps == ()
    assert "not supported" in plan.reason


def test_planner_normalizes_single_step_web_payload():
    planner = PlannerService()

    understanding = {
        "intent": "web",
        "requires_tool": True,
        "web_action": "search",
        "web_topic": "news",
        "web_time_range": "day",
        "query": "latest AI news",
        "max_results": "5",
    }

    available_tools = [
        {
            "name": "web",
            "description": "Search live web information.",
            "actions": ["search"],
        }
    ]

    plan = planner.create_plan(
        understanding=understanding,
        available_tools=available_tools,
    )

    assert plan.requires_tool is True
    assert plan.tool == "web"
    assert plan.action == "search"

    assert plan.data["query"] == "latest AI news"
    assert plan.data["topic"] == "news"
    assert plan.data["time_range"] == "day"
    assert plan.data["web_topic"] == "news"
    assert plan.data["web_time_range"] == "day"
    assert plan.data["max_results"] == 5
    assert plan.data["action"] == "search"
    assert plan.data["web_action"] == "search"

    assert plan.steps[0].data["topic"] == "news"
    assert plan.steps[0].data["time_range"] == "day"


def test_planner_normalizes_multi_step_web_payload():
    planner = PlannerService()

    available_tools = [
        {
            "name": "web",
            "description": "Search live web information.",
            "actions": ["search"],
        }
    ]

    plan = planner.create_multi_step_plan(
        steps=[
            {
                "step_id": "step-1",
                "tool": "web",
                "action": "search",
                "data": {
                    "web_action": "search",
                    "web_topic": "finance",
                    "web_time_range": "week",
                    "query": "USD to PKR exchange rate",
                    "max_results": 3,
                },
                "depends_on": [],
            }
        ],
        available_tools=available_tools,
    )

    assert plan.requires_tool is True
    assert len(plan.steps) == 1

    step = plan.steps[0]

    assert step.data["query"] == "USD to PKR exchange rate"
    assert step.data["topic"] == "finance"
    assert step.data["time_range"] == "week"
    assert step.data["web_topic"] == "finance"
    assert step.data["web_time_range"] == "week"
    assert step.data["max_results"] == 3
    assert step.data["action"] == "search"
    assert step.data["web_action"] == "search"


def test_planner_rejects_web_search_without_query():
    planner = PlannerService()

    available_tools = [
        {
            "name": "web",
            "description": "Search live web information.",
            "actions": ["search"],
        }
    ]

    plan = planner.create_multi_step_plan(
        steps=[
            {
                "step_id": "step-1",
                "tool": "web",
                "action": "search",
                "data": {
                    "web_topic": "news",
                },
                "depends_on": [],
            }
        ],
        available_tools=available_tools,
    )

    assert plan.requires_tool is False
    assert plan.tool is None
    assert plan.action is None
    assert plan.steps == ()
    assert "requires a non-empty query" in plan.reason


@pytest.mark.parametrize(
    "field,value",
    [
        ("web_topic", "sports"),
        ("web_time_range", "hour"),
        ("max_results", 11),
        ("max_results", 0),
    ],
)
def test_planner_rejects_invalid_web_search_payload(field, value):
    planner = PlannerService()

    data = {
        "query": "AI news",
        "web_topic": "general",
        "web_time_range": "day",
        "max_results": 5,
    }
    data[field] = value

    plan = planner.create_multi_step_plan(
        steps=[
            {
                "step_id": "step-1",
                "tool": "web",
                "action": "search",
                "data": data,
                "depends_on": [],
            }
        ],
        available_tools=[
            {
                "name": "web",
                "description": "Search live web information.",
                "actions": ["search"],
            }
        ],
    )

    assert plan.requires_tool is False
    assert plan.steps == ()
    assert "invalid" in plan.reason
