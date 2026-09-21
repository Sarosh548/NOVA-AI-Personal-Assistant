from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.permissions as permissions_module
from api.auth import (
    AuthenticatedContext,
    get_current_auth_context,
)
from api.permissions import (
    get_permission_service,
    router as permission_router,
)


class FakePermissionService:
    def __init__(self):
        self.permissions = [
            {
                "id": 1,
                "tool": "task",
                "action": "create",
                "mode": "confirm",
                "created_at": datetime(
                    2026,
                    9,
                    21,
                    10,
                    0,
                ),
                "updated_at": datetime(
                    2026,
                    9,
                    21,
                    10,
                    0,
                ),
            }
        ]

    def list_permissions(
        self,
        *,
        user_id,
    ):
        return list(self.permissions)

    def set_permission(
        self,
        *,
        user_id,
        tool,
        action,
        mode,
    ):
        normalized_tool = tool.strip().lower()
        normalized_action = action.strip().lower()

        for permission in self.permissions:
            if (
                permission["tool"] == normalized_tool
                and permission["action"] == normalized_action
            ):
                permission["mode"] = mode
                return True

        self.permissions.append(
            {
                "id": len(self.permissions) + 1,
                "tool": normalized_tool,
                "action": normalized_action,
                "mode": mode,
                "created_at": datetime(
                    2026,
                    9,
                    21,
                    10,
                    1,
                ),
                "updated_at": datetime(
                    2026,
                    9,
                    21,
                    10,
                    1,
                ),
            }
        )
        return True

    def delete_permission(
        self,
        *,
        user_id,
        tool,
        action,
    ):
        normalized_tool = tool.strip().lower()
        normalized_action = action.strip().lower()

        original = len(self.permissions)
        self.permissions = [
            item
            for item in self.permissions
            if not (
                item["tool"] == normalized_tool
                and item["action"] == normalized_action
            )
        ]
        return len(self.permissions) < original


class FakeAuditService:
    def __init__(self):
        self.events = []

    def record_event(self, **kwargs):
        self.events.append(kwargs)
        return {
            "id": len(self.events),
            **kwargs,
        }


def build_client():
    permission_service = FakePermissionService()
    audit_service = FakeAuditService()

    permissions_module.audit_service = audit_service

    app = FastAPI()
    app.include_router(permission_router)

    now = datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )

    context = AuthenticatedContext(
        user=type(
            "FakeUser",
            (),
            {
                "id": "audit-permission-user",
                "is_active": True,
            },
        )(),
        session=type(
            "FakeSession",
            (),
            {
                "id": "audit-permission-session",
                "expires_at": now.replace(
                    year=now.year + 1
                ),
                "revoked_at": None,
            },
        )(),
    )

    app.dependency_overrides[
        get_current_auth_context
    ] = lambda: context

    app.dependency_overrides[
        get_permission_service
    ] = lambda: permission_service

    return (
        TestClient(app),
        permission_service,
        audit_service,
        app,
    )


def test_permission_change_writes_audit_event():
    client, _, audit_service, app = build_client()

    try:
        response = client.put(
            "/permissions/task/create",
            json={
                "mode": "allow",
            },
            headers={
                "X-Request-ID": "permission-audit-request",
            },
        )

        assert response.status_code == 200
        assert len(audit_service.events) == 1

        event = audit_service.events[0]

        assert event["event_type"] == "authorization"
        assert event["action"] == "set"
        assert event["status"] == "success"
        assert event["user_id"] == "audit-permission-user"
        assert event["resource_type"] == "permission"
        assert event["metadata"] == {
            "tool": "task",
            "permission_action": "create",
            "mode": "allow",
        }

    finally:
        app.dependency_overrides.clear()


def test_permission_deletion_writes_audit_event():
    client, _, audit_service, app = build_client()

    try:
        response = client.delete(
            "/permissions/task/create",
            headers={
                "X-Request-ID": "permission-audit-delete",
            },
        )

        assert response.status_code == 204
        assert len(audit_service.events) == 1

        event = audit_service.events[0]

        assert event["event_type"] == "authorization"
        assert event["action"] == "delete"
        assert event["status"] == "success"
        assert event["user_id"] == "audit-permission-user"

    finally:
        app.dependency_overrides.clear()
