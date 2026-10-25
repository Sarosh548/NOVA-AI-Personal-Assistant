from services.notification_service import NotificationService
from services.tool_router import ToolRouter


class FakeEmailDelivery:
    def __init__(self):
        self.calls = []

    def send_email(self, **kwargs):
        self.calls.append(kwargs)
        return True


def test_email_tool_is_discoverable():
    router = ToolRouter(
        notification_service=NotificationService()
    )

    email = next(
        tool for tool in router.get_available_tools()
        if tool["name"] == "email"
    )

    assert email["actions"] == ["send", "list", "search", "get"]


def test_email_tool_sends_requested_message():
    delivery = FakeEmailDelivery()
    notification_service = NotificationService()
    notification_service.channel_registry.register(
        "email",
        delivery,
    )

    router = ToolRouter(
        notification_service=notification_service
    )

    result = router.execute(
        intent="email",
        user_id="user-001",
        data={
            "action": "send",
            "to": "recipient@example.com",
            "subject": "Hello",
            "body": "Hello from NOVA.",
            "cc": ["copy@example.com"],
        },
    )

    assert result["success"] is True
    assert result["tool"] == "email"
    assert result["action"] == "send"
    assert result["result"]["status"] == "accepted_by_smtp"
    assert result["result"]["subject"] == "Hello"

    assert delivery.calls == [
        {
            "user_id": "user-001",
            "to": "recipient@example.com",
            "subject": "Hello",
            "body": "Hello from NOVA.",
            "cc": ["copy@example.com"],
            "bcc": None,
        }
    ]


def test_email_tool_requires_subject_and_body():
    router = ToolRouter(
        notification_service=NotificationService()
    )

    missing_subject = router.execute(
        intent="email",
        user_id="user-001",
        data={
            "action": "send",
            "to": "recipient@example.com",
            "body": "Hello.",
        },
    )

    missing_body = router.execute(
        intent="email",
        user_id="user-001",
        data={
            "action": "send",
            "to": "recipient@example.com",
            "subject": "Hello",
        },
    )

    assert missing_subject["success"] is False
    assert missing_subject["error"] == "Email subject is missing."

    assert missing_body["success"] is False
    assert missing_body["error"] == "Email body is missing."


def test_email_tool_does_not_treat_failed_provider_status_as_success():
    class ProviderResultService:
        def __init__(self, status):
            self.status = status

        def send_email_result(self, **kwargs):
            return {"status": self.status}

    class NoopActivityService:
        def record_event(self, **kwargs):
            return None

    for status in ("failed", "rejected", "pending", "", None):
        router = ToolRouter(
            notification_service=ProviderResultService(status),
            activity_event_service=NoopActivityService(),
        )
        result = router.execute(
            intent="email",
            user_id="user-001",
            data={
                "action": "send",
                "to": "recipient@example.com",
                "subject": "Hello",
                "body": "Hello from NOVA.",
            },
        )

        assert result["success"] is False, status
        assert result["error"] == (
            "Email delivery failed. No successful provider acceptance was confirmed."
        )


def test_email_tool_lists_messages_through_connected_gmail_reader():
    calls = []

    class FakeMailReader:
        def list_messages(self, **kwargs):
            calls.append(("list", kwargs))
            return {"count": 1, "messages": [{"id": "message_123"}]}

        def get_message(self, **kwargs):
            calls.append(("get", kwargs))
            return {"id": kwargs["message_id"], "subject": "Hello"}

    notification_service = NotificationService()
    notification_service.google_mail_service = FakeMailReader()
    router = ToolRouter(notification_service=notification_service)

    result = router.execute(
        intent="email",
        user_id="user-001",
        data={
            "email_action": "search",
            "query": "invoice",
            "max_results": 3,
        },
    )

    assert result["success"] is True
    assert result["action"] == "search"
    assert result["result"]["messages"][0]["id"] == "message_123"
    assert calls == [("list", {
        "user_id": "user-001",
        "query": "invoice",
        "max_results": 3,
        "include_body": False,
    })]


def test_email_tool_includes_message_body_only_for_explicit_read_or_summary():
    calls = []

    class FakeMailReader:
        def list_messages(self, **kwargs):
            calls.append(kwargs)
            return {"count": 1, "messages": [{
                "id": "message_123",
                "subject": "Deadline",
                "body": "The deadline is Friday.",
            }]}

        def get_message(self, **kwargs):
            raise AssertionError("Listing with body content must not perform an unrelated message lookup")

    notification_service = NotificationService()
    notification_service.google_mail_service = FakeMailReader()
    router = ToolRouter(notification_service=notification_service)

    result = router.execute(
        intent="email",
        user_id="user-001",
        data={
            "email_action": "list",
            "include_body": True,
            "max_results": 1,
        },
    )

    assert result["success"] is True
    assert result["result"]["messages"][0]["body"] == "The deadline is Friday."
    assert calls == [{
        "user_id": "user-001",
        "query": None,
        "max_results": 1,
        "include_body": True,
    }]


def test_email_tool_reads_only_the_requested_message_id():
    calls = []

    class FakeMailReader:
        def list_messages(self, **kwargs):
            raise AssertionError("get must not list the mailbox")

        def get_message(self, **kwargs):
            calls.append(kwargs)
            return {"id": kwargs["message_id"], "subject": "Hello"}

    notification_service = NotificationService()
    notification_service.google_mail_service = FakeMailReader()
    router = ToolRouter(notification_service=notification_service)

    result = router.execute(
        intent="email",
        user_id="user-001",
        data={
            "email_action": "get",
            "message_id": "message_123",
        },
    )

    assert result["success"] is True
    assert result["result"]["subject"] == "Hello"
    assert calls == [{
        "user_id": "user-001",
        "message_id": "message_123",
    }]
