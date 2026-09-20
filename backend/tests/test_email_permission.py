import pytest

from services.permission_service import PermissionService


def test_send_is_valid_permission_action():
    service = PermissionService()

    assert service.set_permission(
        user_id="user-001",
        tool="email",
        action="send",
        mode="allow",
    ) is True


def test_email_send_still_requires_high_risk_confirmation():
    service = PermissionService()

    decision = service.check_permission(
        user_id="user-001",
        tool="email",
        action="send",
        user_requested=True,
        execution_mode="interactive",
    )

    assert decision.allowed is True
    assert decision.requires_confirmation is True
    assert decision.risk_level == "high"
