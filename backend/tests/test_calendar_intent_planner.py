from services.agent_planner_service import (
    AgentPlannerService,
)
from services.intent_service import IntentService
from services.planner_service import (
    PlanStep,
    PlannerService,
)


def make_intent_service():
    return IntentService.__new__(
        IntentService
    )


def test_intent_defaults_calendar_fields_safely():
    service = make_intent_service()

    result = service._default_result()

    assert result["intent"] == "chat"
    assert result["calendar_action"] is None
    assert result["event_id"] is None
    assert result["event"] is None
    assert result["time_min"] is None
    assert result["time_max"] is None
    assert result["requires_tool"] is False


def test_intent_validates_calendar_create_payload():
    service = make_intent_service()

    result = {
        "intent": "calendar",
        "calendar_action": "create",
        "calendar_id": "primary",
        "event_id": None,
        "event": {
            "summary": "Team meeting",
            "start": {
                "dateTime": "2026-09-21T15:00:00+05:00",
            },
            "end": {
                "dateTime": "2026-09-21T16:00:00+05:00",
            },
        },
        "send_updates": "all",
        "requires_tool": True,
    }

    validated = service._validate_result(result)

    assert validated["intent"] == "calendar"
    assert validated["calendar_action"] == "create"
    assert validated["calendar_id"] == "primary"
    assert validated["event_id"] is None
    assert validated["event"]["summary"] == "Team meeting"
    assert validated["send_updates"] == "all"
    assert validated["requires_tool"] is True


def test_intent_rejects_invalid_calendar_action_and_fields():
    service = make_intent_service()

    result = {
        "intent": "calendar",
        "calendar_action": "send",
        "calendar_id": 123,
        "event_id": 456,
        "event": "not-an-object",
        "max_results": 5000,
        "single_events": "yes",
        "order_by": "invalid",
        "show_deleted": "no",
        "send_updates": "invalid",
        "requires_tool": True,
    }

    validated = service._validate_result(result)

    assert validated["intent"] == "calendar"
    assert validated["calendar_action"] is None
    assert validated["calendar_id"] == "123"
    assert validated["event_id"] == "456"
    assert validated["event"] is None
    assert validated["max_results"] is None
    assert validated["single_events"] is None
    assert validated["order_by"] is None
    assert validated["show_deleted"] is None
    assert validated["send_updates"] is None
    assert validated["requires_tool"] is True


def test_intent_removes_calendar_fields_from_non_calendar_intent():
    service = make_intent_service()

    result = {
        "intent": "task",
        "task_action": "create",
        "calendar_action": "create",
        "calendar_id": "primary",
        "event_id": "evt-1",
        "event": {
            "summary": "Wrong scope",
        },
        "time_min": "2026-09-21T00:00:00+05:00",
        "requires_tool": True,
    }

    validated = service._validate_result(result)

    assert validated["intent"] == "task"
    assert validated["calendar_action"] is None
    assert validated["calendar_id"] is None
    assert validated["event_id"] is None
    assert validated["event"] is None
    assert validated["time_min"] is None


def test_planner_creates_calendar_plan():
    planner = PlannerService()

    understanding = {
        "intent": "calendar",
        "requires_tool": True,
        "calendar_action": "create",
        "event": {
            "summary": "Team meeting",
            "start": {
                "dateTime": "2026-09-21T15:00:00+05:00",
            },
            "end": {
                "dateTime": "2026-09-21T16:00:00+05:00",
            },
        },
    }

    available_tools = [
        {
            "name": "calendar",
            "description": (
                "Manage Google Calendar events."
            ),
            "actions": [
                "list",
                "get",
                "create",
                "update",
                "delete",
            ],
        }
    ]

    plan = planner.create_plan(
        understanding=understanding,
        available_tools=available_tools,
    )

    assert plan.requires_tool is True
    assert plan.tool == "calendar"
    assert plan.action == "create"
    assert plan.data["calendar_action"] == "create"
    assert plan.data["tool"] == "calendar"
    assert plan.data["action"] == "create"
    assert plan.data["event"]["summary"] == "Team meeting"

    assert plan.steps == (
        PlanStep(
            step_id="step-1",
            tool="calendar",
            action="create",
            data=plan.data,
            depends_on=(),
        ),
    )


def test_planner_maps_calendar_list_action():
    planner = PlannerService()

    plan = planner.create_plan(
        understanding={
            "intent": "calendar",
            "requires_tool": True,
            "calendar_action": "list",
            "time_min": "2026-09-21T00:00:00+05:00",
            "time_max": "2026-09-22T00:00:00+05:00",
        },
        available_tools=[
            {
                "name": "calendar",
                "description": "Manage Google Calendar.",
                "actions": ["list", "get", "create"],
            }
        ],
    )

    assert plan.requires_tool is True
    assert plan.tool == "calendar"
    assert plan.action == "list"
    assert plan.steps[0].tool == "calendar"
    assert plan.steps[0].action == "list"
    assert plan.steps[0].data["calendar_action"] == "list"


def test_planner_rejects_unsupported_calendar_action():
    planner = PlannerService()

    plan = planner.create_plan(
        understanding={
            "intent": "calendar",
            "requires_tool": True,
            "calendar_action": "publish",
        },
        available_tools=[
            {
                "name": "calendar",
                "description": "Manage Google Calendar.",
                "actions": [
                    "list",
                    "get",
                    "create",
                    "update",
                    "delete",
                ],
            }
        ],
    )

    assert plan.requires_tool is False
    assert plan.tool is None
    assert plan.action is None
    assert plan.steps == ()
    assert "No valid action" in plan.reason


class FakeLLMService:
    def __init__(self, response):
        self.response = response
        self.instructions = None

    def generate_with_instructions(
        self,
        *,
        instructions,
        user_input,
    ):
        self.instructions = instructions
        return self.response


def test_agent_planner_accepts_calendar_create_plan():
    llm = FakeLLMService(
        response="""
{
  "requires_tool": true,
  "steps": [
    {
      "step_id": "step-1",
      "tool": "calendar",
      "action": "create",
      "data": {
        "calendar_action": "create",
        "event": {
          "summary": "Team meeting",
          "start": {
            "dateTime": "2026-09-21T15:00:00+05:00"
          },
          "end": {
            "dateTime": "2026-09-21T16:00:00+05:00"
          }
        }
      },
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
        user_message=(
            "Schedule a team meeting tomorrow at 3 PM "
            "for one hour."
        ),
        understanding={
            "intent": "calendar",
            "requires_tool": True,
        },
        history=[],
        available_tools=[
            {
                "name": "calendar",
                "description": "Manage Google Calendar events.",
                "actions": [
                    "list",
                    "get",
                    "create",
                    "update",
                    "delete",
                ],
            }
        ],
    )

    assert result.requires_tool is True
    assert result.tool == "calendar"
    assert result.action == "create"
    assert len(result.steps) == 1
    assert result.steps[0].tool == "calendar"
    assert result.steps[0].action == "create"


def test_agent_planner_prompt_contains_calendar_rules():
    llm = FakeLLMService(
        response='{"requires_tool": false, "steps": []}'
    )

    service = AgentPlannerService(
        llm_service=llm,
    )

    service.create_plan(
        user_message="What's on my calendar tomorrow?",
        understanding={
            "intent": "calendar",
            "requires_tool": True,
        },
        history=[],
        available_tools=[
            {
                "name": "calendar",
                "description": "Manage Google Calendar events.",
                "actions": [
                    "list",
                    "get",
                    "create",
                    "update",
                    "delete",
                ],
            }
        ],
    )

    assert llm.instructions is not None
    assert "For calendar:" in llm.instructions
    assert 'calendar_action="create"' in llm.instructions
    assert "time_min/time_max" in llm.instructions
    assert "attendees" in llm.instructions
    assert "event_id" in llm.instructions
