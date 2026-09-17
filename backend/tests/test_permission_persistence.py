from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.permission import Permission
from services.permission_service import (
    PermissionService,
)
import services.permission_service as permission_service_module


def _create_test_engine():
    return create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )


def _prepare_permission_database(
    monkeypatch,
):
    test_engine = _create_test_engine()

    Permission.__table__.create(
        bind=test_engine
    )

    monkeypatch.setattr(
        permission_service_module,
        "engine",
        test_engine,
    )

    return test_engine


def test_set_and_get_permission(
    monkeypatch,
):
    test_engine = _prepare_permission_database(
        monkeypatch
    )

    try:
        service = PermissionService()

        result = service.set_permission(
            user_id="test-user",
            tool="task",
            action="create",
            mode="allow",
        )

        assert result is True

        assert (
            service.get_permission(
                user_id="test-user",
                tool="task",
                action="create",
            )
            == "allow"
        )

    finally:
        test_engine.dispose()


def test_set_permission_updates_existing_record(
    monkeypatch,
):
    test_engine = _prepare_permission_database(
        monkeypatch
    )

    try:
        service = PermissionService()

        service.set_permission(
            user_id="test-user",
            tool="task",
            action="create",
            mode="allow",
        )

        service.set_permission(
            user_id="test-user",
            tool="task",
            action="create",
            mode="deny",
        )

        permissions = service.list_permissions(
            user_id="test-user"
        )

        assert len(permissions) == 1
        assert permissions[0]["tool"] == "task"
        assert permissions[0]["action"] == "create"
        assert permissions[0]["mode"] == "deny"

    finally:
        test_engine.dispose()


def test_list_permissions_returns_user_permissions(
    monkeypatch,
):
    test_engine = _prepare_permission_database(
        monkeypatch
    )

    try:
        service = PermissionService()

        service.set_permission(
            user_id="test-user",
            tool="task",
            action="create",
            mode="allow",
        )

        service.set_permission(
            user_id="test-user",
            tool="task",
            action="delete",
            mode="deny",
        )

        permissions = service.list_permissions(
            user_id="test-user"
        )

        assert len(permissions) == 2

        assert {
            (
                item["tool"],
                item["action"],
                item["mode"],
            )
            for item in permissions
        } == {
            ("task", "create", "allow"),
            ("task", "delete", "deny"),
        }

    finally:
        test_engine.dispose()


def test_delete_permission_removes_saved_permission(
    monkeypatch,
):
    test_engine = _prepare_permission_database(
        monkeypatch
    )

    try:
        service = PermissionService()

        service.set_permission(
            user_id="test-user",
            tool="task",
            action="create",
            mode="allow",
        )

        deleted = service.delete_permission(
            user_id="test-user",
            tool="task",
            action="create",
        )

        assert deleted is True

        assert (
            service.get_permission(
                user_id="test-user",
                tool="task",
                action="create",
            )
            is None
        )

    finally:
        test_engine.dispose()


def test_delete_missing_permission_returns_false(
    monkeypatch,
):
    test_engine = _prepare_permission_database(
        monkeypatch
    )

    try:
        service = PermissionService()

        result = service.delete_permission(
            user_id="test-user",
            tool="task",
            action="create",
        )

        assert result is False

    finally:
        test_engine.dispose()


def test_saved_allow_permission_allows_background_action(
    monkeypatch,
):
    test_engine = _prepare_permission_database(
        monkeypatch
    )

    try:
        service = PermissionService()

        service.set_permission(
            user_id="test-user",
            tool="task",
            action="create",
            mode="allow",
        )

        decision = service.check(
            user_id="test-user",
            tool="task",
            action="create",
            user_requested=False,
        )

        assert decision.allowed is True
        assert (
            decision.requires_confirmation
            is False
        )

    finally:
        test_engine.dispose()


def test_saved_confirm_permission_requires_confirmation(
    monkeypatch,
):
    test_engine = _prepare_permission_database(
        monkeypatch
    )

    try:
        service = PermissionService()

        service.set_permission(
            user_id="test-user",
            tool="task",
            action="delete",
            mode="confirm",
        )

        decision = service.check(
            user_id="test-user",
            tool="task",
            action="delete",
            user_requested=False,
        )

        assert decision.allowed is False
        assert (
            decision.requires_confirmation
            is True
        )

    finally:
        test_engine.dispose()


def test_saved_deny_permission_blocks_action(
    monkeypatch,
):
    test_engine = _prepare_permission_database(
        monkeypatch
    )

    try:
        service = PermissionService()

        service.set_permission(
            user_id="test-user",
            tool="task",
            action="delete",
            mode="deny",
        )

        decision = service.check(
            user_id="test-user",
            tool="task",
            action="delete",
            user_requested=False,
        )

        assert decision.allowed is False
        assert (
            decision.requires_confirmation
            is False
        )

    finally:
        test_engine.dispose()