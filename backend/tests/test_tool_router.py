from services.tool_router import ToolRouter


def test_tool_router_registers_default_tools():
    router = ToolRouter()

    tools = router.get_available_tools()

    assert tools == [
        {
            "name": "reminder",
            "description": (
                "Create, list, complete, cancel, "
                "delete, and update reminders."
            ),
            "actions": [
                "create",
                "list",
                "complete",
                "cancel",
                "delete",
                "update",
            ],
        },
        {
            "name": "task",
            "description": (
                "Create, list, start, complete, "
                "cancel, delete, and update tasks."
            ),
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
            "name": "email",
            "description": (
                "Send outbound email messages to recipients "
                "using NOVA's configured email provider."
            ),
            "actions": [
                "send",
            ],
        },
    ]


def test_tool_router_uses_registry_for_unknown_tool():
    router = ToolRouter()

    result = router.execute(
        intent="calendar",
        user_id="user-001",
        data={},
    )

    assert result["success"] is False
    assert result["tool"] is None
    assert result["action"] is None
    assert result["result"] is None
    assert (
        result["error"]
        == "No tool is registered for name 'calendar'."
    )


def test_tool_router_can_register_and_execute_custom_tool():
    router = ToolRouter()

    def custom_tool(
        user_id: str,
        data: dict,
    ) -> dict:
        return {
            "success": True,
            "tool": "custom",
            "action": "execute",
            "result": {
                "message": data["message"],
                "user_id": user_id,
            },
            "error": None,
        }

    router.registry.register(
        name="custom",
        description="A custom test tool.",
        actions=("execute",),
        handler=custom_tool,
    )

    tools = router.get_available_tools()

    assert {
        "name": "custom",
        "description": "A custom test tool.",
        "actions": ["execute"],
    } in tools

    result = router.execute(
        intent="custom",
        user_id="user-001",
        data={
            "message": "hello from custom tool",
        },
    )

    assert result["success"] is True
    assert result["tool"] == "custom"
    assert result["action"] == "execute"
    assert (
        result["result"]["message"]
        == "hello from custom tool"
    )
    assert result["result"]["user_id"] == "user-001"
    assert result["error"] is None