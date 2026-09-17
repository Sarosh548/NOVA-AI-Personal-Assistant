from services.agent_planner_service import (
    AgentPlannerService,
)


class FakeLLMService:
    def __init__(
        self,
        response,
        should_fail=False,
    ):
        self.response = response
        self.should_fail = should_fail
        self.received_instructions = None
        self.received_user_input = None

    def generate_with_instructions(
        self,
        *,
        instructions,
        user_input,
    ):
        self.received_instructions = instructions
        self.received_user_input = user_input

        if self.should_fail:
            raise RuntimeError(
                "Simulated LLM failure."
            )

        return self.response


def available_tools():
    return [
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
        },
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
        },
    ]


def test_agent_planner_creates_valid_multi_step_plan():
    llm = FakeLLMService(
        response="""
{
  "requires_tool": true,
  "steps": [
    {
      "step_id": "step-1",
      "tool": "task",
      "action": "list",
      "data": {},
      "depends_on": []
    },
    {
      "step_id": "step-2",
      "tool": "reminder",
      "action": "create",
      "data": {
        "reminder_action": "create",
        "task": "Review my tasks",
        "scheduled_at": "2026-09-18T20:00:00+05:00"
      },
      "depends_on": ["step-1"]
    }
  ]
}
""",
    )

    service = AgentPlannerService(
        llm_service=llm,
    )

    result = service.create_plan(
        user_message=(
            "Show me my tasks and remind me at 8 PM "
            "to review them."
        ),
        understanding={
            "intent": "planning",
            "requires_tool": True,
        },
        history=[],
        available_tools=available_tools(),
    )

    assert result.requires_tool is True
    assert result.tool is None
    assert result.action is None

    assert len(result.steps) == 2

    assert result.steps[0].step_id == "step-1"
    assert result.steps[0].tool == "task"
    assert result.steps[0].action == "list"
    assert result.steps[0].depends_on == ()

    assert result.steps[1].step_id == "step-2"
    assert result.steps[1].tool == "reminder"
    assert result.steps[1].action == "create"
    assert result.steps[1].depends_on == (
        "step-1",
    )


def test_agent_planner_rejects_llm_unknown_tool():
    llm = FakeLLMService(
        response="""
{
  "requires_tool": true,
  "steps": [
    {
      "step_id": "step-1",
      "tool": "email",
      "action": "send",
      "data": {},
      "depends_on": []
    }
  ]
}
""",
    )

    service = AgentPlannerService(
        llm_service=llm,
    )

    result = service.create_plan(
        user_message="Send an email.",
        understanding={
            "intent": "action",
            "requires_tool": True,
        },
        history=[],
        available_tools=available_tools(),
    )

    assert result.requires_tool is False
    assert result.steps == ()
    assert "not currently available" in result.reason


def test_agent_planner_rejects_llm_unsupported_action():
    llm = FakeLLMService(
        response="""
{
  "requires_tool": true,
  "steps": [
    {
      "step_id": "step-1",
      "tool": "task",
      "action": "send",
      "data": {},
      "depends_on": []
    }
  ]
}
""",
    )

    service = AgentPlannerService(
        llm_service=llm,
    )

    result = service.create_plan(
        user_message="Send the task somewhere.",
        understanding={
            "intent": "action",
            "requires_tool": True,
        },
        history=[],
        available_tools=available_tools(),
    )

    assert result.requires_tool is False
    assert result.steps == ()
    assert "not supported" in result.reason


def test_agent_planner_handles_invalid_llm_json_with_fallback():
    llm = FakeLLMService(
        response="This is not JSON.",
    )

    service = AgentPlannerService(
        llm_service=llm,
    )

    result = service.create_plan(
        user_message=(
            "Create a task to practice Python."
        ),
        understanding={
            "intent": "task",
            "requires_tool": True,
            "task_action": "create",
            "task": "Practice Python",
        },
        history=[],
        available_tools=available_tools(),
    )

    assert result.requires_tool is True
    assert result.tool == "task"
    assert result.action == "create"
    assert len(result.steps) == 1
    assert result.steps[0].step_id == "step-1"


def test_agent_planner_handles_llm_failure_with_fallback():
    llm = FakeLLMService(
        response="",
        should_fail=True,
    )

    service = AgentPlannerService(
        llm_service=llm,
    )

    result = service.create_plan(
        user_message=(
            "Create a task to practice Python."
        ),
        understanding={
            "intent": "task",
            "requires_tool": True,
            "task_action": "create",
            "task": "Practice Python",
        },
        history=[],
        available_tools=available_tools(),
    )

    assert result.requires_tool is True
    assert result.tool == "task"
    assert result.action == "create"
    assert len(result.steps) == 1


def test_agent_planner_returns_safe_empty_plan_for_no_tool_request():
    llm = FakeLLMService(
        response="""
{
  "requires_tool": false,
  "steps": []
}
""",
    )

    service = AgentPlannerService(
        llm_service=llm,
    )

    result = service.create_plan(
        user_message="Hello NOVA",
        understanding={
            "intent": "chat",
            "requires_tool": False,
        },
        history=[],
        available_tools=available_tools(),
    )

    assert result.requires_tool is False
    assert result.tool is None
    assert result.action is None
    assert result.steps == ()


def test_agent_planner_includes_tools_and_message_in_prompt():
    llm = FakeLLMService(
        response="""
{
  "requires_tool": false,
  "steps": []
}
""",
    )

    service = AgentPlannerService(
        llm_service=llm,
    )

    service.create_plan(
        user_message="Create a task to learn LangGraph.",
        understanding={
            "intent": "planning",
            "requires_tool": True,
        },
        history=[
            {
                "role": "user",
                "content": (
                    "I am preparing for an AI interview."
                ),
            }
        ],
        available_tools=available_tools(),
    )

    assert llm.received_instructions is not None

    assert (
        "Create a task to learn LangGraph."
        in llm.received_instructions
    )

    assert (
        "I am preparing for an AI interview."
        in llm.received_instructions
    )

    assert '"name": "task"' in (
        llm.received_instructions
    )

    assert '"name": "reminder"' in (
        llm.received_instructions
    )

    assert (
        llm.received_user_input
        == "Create a task to learn LangGraph."
    )