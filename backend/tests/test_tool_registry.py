from services.tool_registry import ToolRegistry


def test_register_and_get_tool():
    registry = ToolRegistry()

    def fake_handler(
        user_id: str,
        data: dict,
    ) -> dict:
        return {
            "success": True,
            "tool": "fake",
            "action": "test",
            "result": {
                "user_id": user_id,
                "data": data,
            },
            "error": None,
        }

    registry.register(
        name="fake",
        description="A fake test tool.",
        actions=("test",),
        handler=fake_handler,
    )

    tool = registry.get("fake")

    assert tool is not None
    assert tool.name == "fake"
    assert tool.description == "A fake test tool."
    assert tool.actions == ("test",)
    assert tool.handler is fake_handler


def test_has_returns_correct_result():
    registry = ToolRegistry()

    def fake_handler(
        user_id: str,
        data: dict,
    ) -> dict:
        return {
            "success": True,
            "tool": "fake",
            "action": "test",
            "result": None,
            "error": None,
        }

    assert registry.has("fake") is False

    registry.register(
        name="fake",
        description="A fake test tool.",
        actions=("test",),
        handler=fake_handler,
    )

    assert registry.has("fake") is True


def test_duplicate_tool_registration_raises_error():
    registry = ToolRegistry()

    def fake_handler(
        user_id: str,
        data: dict,
    ) -> dict:
        return {
            "success": True,
            "tool": "fake",
            "action": "test",
            "result": None,
            "error": None,
        }

    registry.register(
        name="fake",
        description="First registration.",
        actions=("test",),
        handler=fake_handler,
    )

    try:
        registry.register(
            name="fake",
            description="Second registration.",
            actions=("test",),
            handler=fake_handler,
        )
        assert False, "Expected ValueError was not raised."
    except ValueError as exc:
        assert "already registered" in str(exc)


def test_empty_tool_name_raises_error():
    registry = ToolRegistry()

    def fake_handler(
        user_id: str,
        data: dict,
    ) -> dict:
        return {
            "success": True,
            "tool": "fake",
            "action": "test",
            "result": None,
            "error": None,
        }

    try:
        registry.register(
            name="   ",
            description="Invalid tool.",
            actions=("test",),
            handler=fake_handler,
        )
        assert False, "Expected ValueError was not raised."
    except ValueError as exc:
        assert "cannot be empty" in str(exc)


def test_list_tools_returns_metadata_with_actions():
    registry = ToolRegistry()

    def first_handler(
        user_id: str,
        data: dict,
    ) -> dict:
        return {
            "success": True,
            "tool": "first",
            "action": "test",
            "result": None,
            "error": None,
        }

    def second_handler(
        user_id: str,
        data: dict,
    ) -> dict:
        return {
            "success": True,
            "tool": "second",
            "action": "test",
            "result": None,
            "error": None,
        }

    registry.register(
        name="first",
        description="First tool.",
        actions=("create", "update"),
        handler=first_handler,
    )

    registry.register(
        name="second",
        description="Second tool.",
        actions=("search", "delete"),
        handler=second_handler,
    )

    tools = registry.list_tools()

    assert tools == [
        {
            "name": "first",
            "description": "First tool.",
            "actions": [
                "create",
                "update",
            ],
        },
        {
            "name": "second",
            "description": "Second tool.",
            "actions": [
                "search",
                "delete",
            ],
        },
    ]

    assert "handler" not in tools[0]
    assert "handler" not in tools[1]


def test_execute_registered_tool():
    registry = ToolRegistry()

    def fake_handler(
        user_id: str,
        data: dict,
    ) -> dict:
        return {
            "success": True,
            "tool": "fake",
            "action": "test",
            "result": {
                "message": data["message"],
                "user_id": user_id,
            },
            "error": None,
        }

    registry.register(
        name="fake",
        description="A fake test tool.",
        actions=("test",),
        handler=fake_handler,
    )

    result = registry.execute(
        name="fake",
        user_id="user-001",
        data={
            "message": "hello NOVA",
        },
    )

    assert result["success"] is True
    assert result["tool"] == "fake"
    assert result["action"] == "test"
    assert result["result"]["message"] == "hello NOVA"
    assert result["result"]["user_id"] == "user-001"
    assert result["error"] is None


def test_execute_unknown_tool_returns_safe_error():
    registry = ToolRegistry()

    result = registry.execute(
        name="does_not_exist",
        user_id="user-001",
        data={},
    )

    assert result["success"] is False
    assert result["tool"] is None
    assert result["action"] is None
    assert result["result"] is None
    assert (
        result["error"]
        == "No tool is registered for name 'does_not_exist'."
    )


def test_unregister_tool():
    registry = ToolRegistry()

    def fake_handler(
        user_id: str,
        data: dict,
    ) -> dict:
        return {
            "success": True,
            "tool": "fake",
            "action": "test",
            "result": None,
            "error": None,
        }

    registry.register(
        name="fake",
        description="A fake test tool.",
        actions=("test",),
        handler=fake_handler,
    )

    assert registry.has("fake") is True

    removed = registry.unregister("fake")

    assert removed is True
    assert registry.has("fake") is False

    removed_again = registry.unregister("fake")

    assert removed_again is False


def test_get_available_tools_returns_registered_tools():
    registry = ToolRegistry()

    def fake_handler(
        user_id: str,
        data: dict,
    ) -> dict:
        return {
            "success": True,
            "tool": "fake",
            "action": "test",
            "result": None,
            "error": None,
        }

    registry.register(
        name="fake",
        description="A fake test tool.",
        actions=("test",),
        handler=fake_handler,
    )

    tools = registry.get_available_tools()

    assert tools == [
        {
            "name": "fake",
            "description": "A fake test tool.",
            "actions": ["test"],
        }
    ]

    assert "handler" not in tools[0]