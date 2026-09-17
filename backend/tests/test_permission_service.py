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


def test_search_action_is_allowed():
    service = PermissionService()

    decision = service.check(
        user_id="user-001",
        tool="web",
        action="search",
    )

    assert decision.allowed is True
    assert decision.requires_confirmation is False


def test_create_action_requires_confirmation():
    service = PermissionService()

    decision = service.check(
        user_id="user-001",
        tool="task",
        action="create",
    )

    assert decision.allowed is False
    assert decision.requires_confirmation is True
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


def test_delete_action_requires_confirmation():
    service = PermissionService()

    decision = service.check(
        user_id="user-001",
        tool="task",
        action="delete",
    )

    assert decision.allowed is False
    assert decision.requires_confirmation is True


def test_unknown_action_is_denied():
    service = PermissionService()

    decision = service.check(
        user_id="user-001",
        tool="email",
        action="send",
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