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

    assert email["actions"] == ["send"]


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
    assert result["result"]["status"] == "sent"
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
