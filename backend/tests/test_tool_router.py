from unittest.mock import Mock

from services.tool_router import ToolRouter


def test_tool_router_registers_default_tools():
    from services.desktop_control_service import DesktopControlService

    # Simulate local Windows development deterministically on every CI host.
    router = ToolRouter(
        desktop_control_service=DesktopControlService(
            enabled=False,
            platform_name="nt",
            environment="development",
        ),
    )

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
                "List and search a connected Gmail inbox, read a selected email, "
                "and send outbound email after NOVA's confirmation policy approves it."
            ),
            "actions": [
                "send",
                "list",
                "search",
                "get",
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
        {
            "name": "desktop",
            "description": (
                "Use the authenticated user's local Windows desktop safely: open an "
                "installed application or HTTP(S) website, launch a web search, open "
                "the allowlisted Local Disk C root or a standard user folder/safe file, "
                "search file names (CV/resume searches include the user's profile), "
                "inspect visible windows/accessibility labels, click one uniquely named "
                "safe UI control, type into one uniquely named non-sensitive field, press an "
                "allowlisted keyboard shortcut, or play a specifically named YouTube video "
                "only when the player exposes a verified playing state. Use exact visible control labels "
                "and a window hint when needed; never guess coordinates, execute shell "
                "commands/scripts, or use generic UI actions to send/delete/publish/pay/"
                "approve/submit an external change. Dedicated integrations and explicit "
                "confirmation are required for consequential actions."
            ),
            "actions": ["start", "search"],
        },
    ]



def test_tool_router_deletes_only_the_confirmed_bulk_task_ids():
    class FakeTaskService:
        def __init__(self):
            self.calls = []

        def delete_tasks(self, *, task_ids, user_id, expected_status=None):
            self.calls.append({
                "task_ids": task_ids,
                "user_id": user_id,
                "expected_status": expected_status,
            })
            return [
                {
                    "id": task_id,
                    "title": f"Task {task_id}",
                    "status": "pending",
                    "priority": "medium",
                }
                for task_id in task_ids
            ]

    task_service = FakeTaskService()
    router = ToolRouter(task_service=task_service)

    result = router.execute(
        intent="task",
        user_id="user-001",
        data={
            "task_action": "delete",
            "bulk_task_delete": True,
            "task_ids": [219, 218, 217],
            "task_status_filter": "pending",
        },
    )

    assert result["success"] is True
    assert result["action"] == "delete"
    assert result["result"]["deleted_count"] == 3
    assert result["result"]["task_ids"] == [219, 218, 217]
    assert task_service.calls == [{
        "task_ids": [219, 218, 217],
        "user_id": "user-001",
        "expected_status": "pending",
    }]


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


def test_email_tool_preserves_gmail_message_receipt():
    class FakeNotificationService:
        def send_email_result(self, **kwargs):
            return {
                "status": "sent",
                "provider": "gmail",
                "message_id": "gmail-message-id",
                "sent_label_confirmed": True,
                "from": "owner@example.com",
                "to": [kwargs["to"]],
                "subject": kwargs["subject"],
            }

    router = ToolRouter(
        notification_service=FakeNotificationService(),
        activity_event_service=Mock(),
    )
    result = router.execute(
        intent="email",
        user_id="user-001",
        data={
            "action": "send",
            "to": "recipient@example.com",
            "subject": "NOVA test",
            "body": "NOVA test successful.",
        },
    )

    assert result["success"] is True
    assert result["result"]["message_id"] == "gmail-message-id"
    assert result["result"]["provider"] == "gmail"
    assert result["result"]["sent_label_confirmed"] is True



def test_tool_router_registers_desktop_for_dev_windows_but_enforces_opt_in(tmp_path):
    from services.desktop_control_service import DesktopControlService

    enabled = DesktopControlService(
        enabled=True,
        platform_name="nt",
        environment="development",
        home_directory=tmp_path,
        process_launcher=lambda command: None,
        url_opener=lambda url: True,
        file_opener=lambda path: None,
    )
    disabled = DesktopControlService(
        enabled=False,
        platform_name="nt",
        environment="development",
        home_directory=tmp_path,
    )
    production = DesktopControlService(
        enabled=True,
        platform_name="nt",
        environment="production",
        home_directory=tmp_path,
    )

    enabled_router = ToolRouter(
        desktop_control_service=enabled,
        activity_event_service=Mock(),
    )
    disabled_router = ToolRouter(
        desktop_control_service=disabled,
        activity_event_service=Mock(),
    )
    production_router = ToolRouter(
        desktop_control_service=production,
        activity_event_service=Mock(),
    )

    assert any(item["name"] == "desktop" for item in enabled_router.get_available_tools())
    assert any(item["name"] == "desktop" for item in disabled_router.get_available_tools())
    assert all(item["name"] != "desktop" for item in production_router.get_available_tools())

    rejected = disabled_router.execute(
        intent="desktop",
        user_id="user-1",
        data={
            "action": "start",
            "desktop_operation": "open_app",
            "desktop_target": "notepad",
        },
    )
    assert rejected["success"] is False
    assert "disabled" in rejected["error"].lower()


def test_tool_router_safely_executes_desktop_app_launch_through_registry(tmp_path):
    from services.desktop_control_service import DesktopControlService

    launched = []
    service = DesktopControlService(
        enabled=True,
        platform_name="nt",
        home_directory=tmp_path,
        process_launcher=lambda command: launched.append(command),
    )
    router = ToolRouter(
        desktop_control_service=service,
        activity_event_service=Mock(),
    )

    result = router.execute(
        intent="desktop",
        user_id="user-1",
        data={
            "action": "start",
            "desktop_operation": "open_app",
            "desktop_target": "calculator",
        },
    )

    assert result["success"] is True
    assert result["tool"] == "desktop"
    assert result["result"]["application"] == "calculator"
    assert launched == [["calc.exe"]]


def test_create_task_result_uses_sanitized_title():
    from services.tool_router import ToolRouter

    raw_title = "Nova Live Test task. 1021 ko due date mat lagana"

    class FakeTaskService:
        def create_task(self, **kwargs):
            assert kwargs["user_id"] == "user-001"
            assert kwargs["title"] == raw_title
            assert kwargs["due_at"] is None
            return 42

    router = ToolRouter(task_service=FakeTaskService())
    result = router._create_task(
        user_id="user-001",
        data={"task": raw_title, "scheduled_at": None},
    )

    assert result["success"] is True
    assert result["result"]["task_id"] == 42
    assert result["result"]["title"] == "Nova Live Test task. 1021"
    assert result["result"]["due_at"] is None


def test_tool_router_returns_safe_web_provider_failure_details():
    class FailingWebSearchService:
        def search(self, **kwargs):
            raise RuntimeError("Google News RSS provider could not be reached.")

    router = ToolRouter(web_search_service=FailingWebSearchService())

    result = router._execute_web(
        user_id="user-001",
        data={"action": "search", "query": "latest AI news", "topic": "news"},
    )

    assert result["success"] is False
    assert result["tool"] == "web"
    assert result["error"] == "Google News RSS provider could not be reached."
