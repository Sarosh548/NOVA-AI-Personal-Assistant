from services.planner_service import PlannerService


def test_planner_accepts_email_send_action():
    planner = PlannerService()

    plan = planner.create_plan(
        understanding={
            "intent": "email",
            "requires_tool": True,
            "email_action": "send",
            "action": "send",
            "to": "recipient@example.com",
            "subject": "Interview update",
            "body": "I wanted to share an update.",
        },
        available_tools=[
            {
                "name": "email",
                "description": "Send outbound email.",
                "actions": ["send"],
            }
        ],
    )

    assert plan.requires_tool is True
    assert plan.tool == "email"
    assert plan.action == "send"
    assert plan.data["tool"] == "email"
    assert plan.data["action"] == "send"
