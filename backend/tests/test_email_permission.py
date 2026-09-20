from services.permission_service import PermissionService


def test_email_send_confirmation_cannot_be_bypassed_by_allow():
    service = PermissionService()
    user_id = "test-email-send-confirmation"

    service.set_permission(
        user_id=user_id,
        tool="email",
        action="send",
        mode="allow",
    )

    try:
        decision = service.check(
            user_id=user_id,
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
        assert "external_communication" in decision.risk_flags
        assert "high_risk_action" in decision.risk_flags

    finally:
        service.delete_permission(
            user_id=user_id,
            tool="email",
            action="send",
        )
