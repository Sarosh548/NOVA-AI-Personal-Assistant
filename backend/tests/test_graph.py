from agent import graph
from agent.graph import (
    understanding_node,
    planner_node,
    route_after_understanding,
)
from services.planner_service import (
    PlanDecision,
    PlanStep,
)


def test_planner_node_creates_task_plan():
    state = {
        "user_id": "user-001",
        "conversation_id": None,
        "user_message": "Create a task to practice Python",
        "history": [],
        "understanding": {
            "intent": "task",
            "requires_tool": True,
            "task_action": "create",
            "task": "Practice Python",
        },
        "plan": {},
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

    result = planner_node(state)

    assert result["plan"]["requires_tool"] is True
    assert result["plan"]["tool"] == "task"
    assert result["plan"]["action"] == "create"
    assert result["plan"]["data"]["task"] == "Practice Python"

    assert len(result["plan"]["steps"]) == 1

    step = result["plan"]["steps"][0]

    assert step["step_id"] == "step-1"
    assert step["tool"] == "task"
    assert step["action"] == "create"
    assert step["data"]["task"] == "Practice Python"
    assert step["depends_on"] == []


def test_planner_node_creates_reminder_plan():
    state = {
        "user_id": "user-001",
        "conversation_id": None,
        "user_message": "Remind me tomorrow to call HR",
        "history": [],
        "understanding": {
            "intent": "reminder",
            "requires_tool": True,
            "reminder_action": "create",
            "task": "Call HR",
            "scheduled_at": "2026-09-17T10:00:00+05:00",
        },
        "plan": {},
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

    result = planner_node(state)

    assert result["plan"]["requires_tool"] is True
    assert result["plan"]["tool"] == "reminder"
    assert result["plan"]["action"] == "create"
    assert result["plan"]["data"]["task"] == "Call HR"

    assert len(result["plan"]["steps"]) == 1

    step = result["plan"]["steps"][0]

    assert step["step_id"] == "step-1"
    assert step["tool"] == "reminder"
    assert step["action"] == "create"
    assert step["data"]["task"] == "Call HR"
    assert step["depends_on"] == []


def test_planner_node_does_not_require_tool_for_chat():
    state = {
        "user_id": "user-001",
        "conversation_id": None,
        "user_message": "Hello NOVA",
        "history": [],
        "understanding": {
            "intent": "chat",
            "requires_tool": False,
        },
        "plan": {},
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

    result = planner_node(state)

    assert result["plan"]["requires_tool"] is False
    assert result["plan"]["tool"] is None
    assert result["plan"]["action"] is None
    assert result["plan"]["steps"] == []


def test_planner_node_uses_agent_planner_for_planning_intent(
    monkeypatch,
):
    calls = []

    class FakeAgentPlannerService:
        def create_plan(
            self,
            *,
            user_message,
            understanding,
            history,
            available_tools,
        ):
            calls.append(
                {
                    "user_message": user_message,
                    "understanding": understanding,
                    "history": history,
                    "available_tools": available_tools,
                }
            )

            return PlanDecision(
                requires_tool=True,
                tool=None,
                action=None,
                data={
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
                            },
                            "depends_on": [
                                "step-1"
                            ],
                        },
                    ]
                },
                reason="Validated 2 executable plan steps.",
                steps=(
                    PlanStep(
                        step_id="step-1",
                        tool="task",
                        action="list",
                        data={},
                        depends_on=(),
                    ),
                    PlanStep(
                        step_id="step-2",
                        tool="reminder",
                        action="create",
                        data={
                            "reminder_action": "create",
                            "task": "Review tasks",
                        },
                        depends_on=(
                            "step-1",
                        ),
                    ),
                ),
            )

    monkeypatch.setattr(
        graph,
        "agent_planner_service",
        FakeAgentPlannerService(),
    )

    history = [
        {
            "role": "user",
            "content": "I want to organize my day.",
        },
    ]

    state = {
        "user_id": "user-001",
        "conversation_id": None,
        "user_message": (
            "Show my tasks and remind me to review them."
        ),
        "history": history,
        "understanding": {
            "intent": "planning",
            "requires_tool": True,
        },
        "plan": {},
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

    result = planner_node(state)

    assert len(calls) == 1

    assert calls[0]["user_message"] == (
        "Show my tasks and remind me to review them."
    )

    assert calls[0]["understanding"]["intent"] == (
        "planning"
    )

    assert calls[0]["history"] == history

    assert result["plan"]["requires_tool"] is True
    assert result["plan"]["tool"] is None
    assert result["plan"]["action"] is None
    assert len(result["plan"]["steps"]) == 2

    first_step = result["plan"]["steps"][0]
    second_step = result["plan"]["steps"][1]

    assert first_step["step_id"] == "step-1"
    assert first_step["tool"] == "task"
    assert first_step["action"] == "list"
    assert first_step["depends_on"] == []

    assert second_step["step_id"] == "step-2"
    assert second_step["tool"] == "reminder"
    assert second_step["action"] == "create"
    assert second_step["depends_on"] == [
        "step-1"
    ]


def test_route_after_understanding_uses_existing_plan_for_tool():
    state = {
        "understanding": {
            "intent": "task",
            "requires_tool": True,
        },
        "plan": {
            "requires_tool": True,
            "tool": "task",
            "action": "complete",
            "data": {
                "task_action": "complete",
            },
            "reason": "Task tool is available.",
        },
    }

    route = route_after_understanding(state)

    assert route == "tool"


def test_route_after_understanding_uses_existing_plan_for_agent():
    state = {
        "understanding": {
            "intent": "chat",
            "requires_tool": False,
        },
        "plan": {
            "requires_tool": False,
            "tool": None,
            "action": None,
            "data": {
                "intent": "chat",
                "requires_tool": False,
            },
            "reason": (
                "The current understanding does not "
                "require an executable tool."
            ),
        },
    }

    route = route_after_understanding(state)

    assert route == "agent"


def test_route_after_understanding_can_create_plan_when_missing():
    state = {
        "understanding": {
            "intent": "task",
            "requires_tool": True,
            "task_action": "complete",
            "task_reference": "Docker task",
        }
    }

    route = route_after_understanding(state)

    assert route == "tool"


def test_understanding_node_passes_message_to_intent_service(
    monkeypatch,
):
    captured = {}

    def fake_analyze(
        message,
        history,
    ):
        captured["message"] = message
        captured["history"] = history

        return {
            "intent": "task",
            "requires_tool": True,
            "task_action": "create",
            "task": "Practice Python",
        }

    monkeypatch.setattr(
        graph.intent_service,
        "analyze",
        fake_analyze,
    )

    history = [
        {
            "role": "user",
            "content": (
                "I want to improve my Python."
            ),
        },
    ]

    state = {
        "user_id": "user-001",
        "conversation_id": None,
        "user_message": "Create a task to practice Python",
        "history": history,
        "understanding": {},
        "plan": {},
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

    result = understanding_node(state)

    assert captured["message"] == (
        "Create a task to practice Python"
    )
    assert captured["history"] == history

    assert "understanding" in result
    assert isinstance(
        result["understanding"],
        dict,
    )
    assert result["understanding"]["intent"] == "task"
    assert result["understanding"]["task_action"] == "create"