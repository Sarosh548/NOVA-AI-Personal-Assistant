from services.permission_service import PermissionService


def test_read_only_action_is_allowed():
    service = PermissionService()

    decision = service.check(
        user_id="user-001",
        tool="task",
        action="list",
    )

    assert decision.allowed is True
    assert decision.requires_confirmation is False
    assert decision.risk_level == "low"
    assert (
        decision.reason
        == "Read-only action 'list' is allowed."
    )


def test_get_action_is_allowed():
    service = PermissionService()

    decision = service.check(
        user_id="user-001",
        tool="calendar",
        action="get",
    )

    assert decision.allowed is True
    assert decision.requires_confirmation is False
    assert decision.risk_level == "low"


def test_search_action_is_allowed():
    service = PermissionService()

    decision = service.check(
        user_id="user-001",
        tool="web",
        action="search",
    )

    assert decision.allowed is True
    assert decision.requires_confirmation is False
    assert decision.risk_level == "low"


def test_create_action_requires_confirmation():
    service = PermissionService()

    decision = service.check(
        user_id="user-001",
        tool="task",
        action="create",
    )

    assert decision.allowed is False
    assert decision.requires_confirmation is True
    assert decision.risk_level == "medium"
    assert "requires confirmation" in decision.reason


def test_update_action_requires_confirmation():
    service = PermissionService()

    decision = service.check(
        user_id="user-001",
        tool="reminder",
        action="update",
    )

    assert decision.allowed is False
    assert decision.requires_confirmation is True
    assert decision.risk_level == "medium"


def test_delete_action_requires_confirmation():
    service = PermissionService()

    decision = service.check(
        user_id="user-001",
        tool="task",
        action="delete",
    )

    assert decision.allowed is False
    assert decision.requires_confirmation is True
    assert decision.risk_level == "medium"


def test_truly_unknown_action_is_denied():
    service = PermissionService()

    decision = service.check(
        user_id="user-001",
        tool="em        action="unknown-action",
    )

    assert decision.allowed is False
    assert decision.requires_confirmation is False
    assert "Unknown action" in decision.reason


def test_missing_tool_is_denied():
    service = PermissionService()

    decision = service.check(
        user_id="user-001",
        tool="",
        action="list",
    )

    assert decision.allowed is False
    assert decision.requires_confirmation is False
    assert decision.reason == "Tool name is missing."


def test_missing_action_is_denied():
    service = PermissionService()

    decision = service.check(
        user_id="user-001",
        tool="task",
        action="",
    )

    assert decision.allowed is False
    assert decision.requires_confirmation is False
    assert decision.reason == "Action name is missing."


def test_explicit_interactive_medium_risk_action_is_allowed():
    service = PermissionService()

    decision = service.check(
        user_id="user-001",
        tool="task",
        action="create",
        user_requested=True,
    )

    assert decision.allowed is True
    assert decision.requires_confirmation is False
    assert decision.risk_level == "medium"


def test_high_risk_tool_requires_confirmation_even_when_interactive():
    service = PermissionService()

    user_id = "risk-test-finance-interactive"

    try:
        decision = service.check(
            user_id=user_id,
            tool="finance",
            action="create",
            user_requested=True,
        )

        assert decision.allowed is False
        assert decision.requires_confirmation is True
        assert decision.risk_level == "high"
        assert "high-risk" in decision.reason.lower()

    finally:
        service.delete_permission(
            user_id=user_id,
            tool="finance",
            action="create",
        )


def test_high_risk_data_requires_confirmation_even_when_interactive():
    service = PermissionService()

    decision = service.check(
        user_id="risk-test-sensitive-data",
        tool="task",
        action="create",
        user_requested=True,
        data={
            "password": "hidden",
        },
    )

    assert decision.allowed is False
    assert decision.requires_confirmation is True
    assert decision.risk_level == "high"
    assert "sensitive_data" in decision.risk_flags


def test_saved_allow_cannot_bypass_high_risk():
    service = PermissionService()

    user_id = "risk-test-saved-allow"

    try:
        service.set_permission(
            user_id=user_id,
            tool="finance",
            action="create",
            mode="allow",
        )

        decision = service.check(
            user_id=user_id,
            tool="finance",
            action="create",
            user_requested=False,
        )

        assert decision.allowed is False
        assert decision.requires_confirmation is True
        assert decision.risk_level == "high"

    finally:
        service.delete_permission(
            user_id=user_id,
            tool="finance",
            action="create",
        )


def test_saved_deny_still_blocks_high_risk():
    service = PermissionService()

    user_id = "risk-test-saved-deny"

    try:
        service.set_permission(
            user_id=user_id,
            tool="finance",
            action="create",
            mode="deny",
        )

        decision = service.check(
            user_id=user_id,
            tool="finance",
            action="create",
            user_requested=True,
        )

        assert decision.allowed is False
        assert decision.requires_confirmation is False
        assert "denied" in decision.reason.lower()

    finally:
        service.delete_permission(
            user_id=user_id,
            tool="finance",
            action="create",
        )