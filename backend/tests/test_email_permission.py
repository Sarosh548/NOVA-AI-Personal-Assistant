from services.permission_service import PermissionService


def test_send_is_valid_permission_action():
    service = PermissionService()

    decision = service.check(
        user_id="user-001",
        tool="email",
        action="send",
        user_requested=True,
        data={
            "to": "recipient@example.com",
            "subject": "Hello",
            "body": "Hello from NOVA.",
        },
    )

    assert decision.allowed is False
    assert decision.requires_confirmation is True
    assert decision.risk_level == "high"
