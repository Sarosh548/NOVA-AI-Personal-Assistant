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
        {
            "name": "web",
            "description": (
                "Search the live public web for "
                "current information and source snippets."
            ),
            "actions": [
                "search",
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

class FakeWebSearchService:
    def __init__(self):
        self.calls = []

    def search(
        self,
        *,
        query,
        max_results,
        topic,
        time_range,
    ):
        self.calls.append(
            {
                "query": query,
                "max_results": max_results,
                "topic": topic,
                "time_range": time_range,
            }
        )

        return [
            {
                "title": "AI News",
                "url": "https://example.com/ai",
                "content": "Fresh AI information.",
                "score": 0.9,
                "published_date": "2026-09-21",
            }
        ]


def test_tool_router_executes_live_web_search():
    web_service = FakeWebSearchService()
    router = ToolRouter(
        web_search_service=web_service,
    )

    result = router.execute(
        intent="web",
        user_id="user-001",
        data={
            "action": "search",
            "query": "latest AI news",
            "max_results": 3,
            "topic": "news",
            "time_range": "day",
        },
    )

    assert result["success"] is True
    assert result["tool"] == "web"
    assert result["action"] == "search"
    assert result["error"] is None
    assert result["result"]["query"] == "latest AI news"
    assert result["result"]["results"][0]["title"] == "AI News"

    assert web_service.calls == [
        {
            "query": "latest AI news",
            "max_results": 3,
            "topic": "news",
            "time_range": "day",
        }
    ]
