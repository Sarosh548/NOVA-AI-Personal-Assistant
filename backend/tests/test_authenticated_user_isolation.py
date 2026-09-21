from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from api.auth import router as auth_router
from api.conversations import router as conversation_router
from api.notification_destinations import (
    router as notification_destination_router,
)
from api.permissions import router as permission_router
from api.reminders import router as reminder_router
from api.tasks import router as task_router
from database.connection import engine
from models.auth_identity import AuthIdentity
from models.user import User
from models.user_session import UserSession


PASSWORD = "CorrectPassword123!"


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(task_router)
    app.include_router(reminder_router)
    app.include_router(conversation_router)
    app.include_router(permission_router)
    app.include_router(
        notification_destination_router
    )
    return app


def _register_user(
    client: TestClient,
    label: str,
) -> dict:
    identifier = (
        f"isolation-{label}-{uuid4().hex[:12]}"
        "@example.test"
    )

    response = client.post(
        "/auth/register",
        json={
            "identifier": identifier,
            "password": PASSWORD,
            "display_name": f"Isolation {label}",
        },
    )

    assert response.status_code == 201

    body = response.json()

    return {
        "id": body["user"]["id"],
        "access_token": body["access_token"],
    }


def _headers(
    access_token: str,
) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
    }


def _cleanup_user(
    client: TestClient,
    user: dict,
    resource_ids: dict[str, int | None],
) -> None:
    headers = _headers(
        user["access_token"]
    )

    if resource_ids["task_id"] is not None:
        response = client.delete(
            f"/tasks/{resource_ids['task_id']}",
            headers=headers,
        )
        assert response.status_code in {
            204,
            404,
        }

    if resource_ids["reminder_id"] is not None:
        response = client.delete(
            f"/reminders/{resource_ids['reminder_id']}",
            headers=headers,
        )
        assert response.status_code in {
            204,
            404,
        }

    if resource_ids["conversation_id"] is not None:
        response = client.delete(
            f"/conversations/{resource_ids['conversation_id']}",
            headers=headers,
        )
        assert response.status_code in {
            204,
            404,
        }

    if resource_ids["permission_tool_create"]:
        response = client.delete(
            "/permissions/task/create",
            headers=headers,
        )
        assert response.status_code in {
            204,
            404,
        }

    if resource_ids["destination_id"] is not None:
        response = client.delete(
            (
                "/notification-destinations/"
                f"{resource_ids['destination_id']}"
            ),
            headers=headers,
        )
        assert response.status_code in {
            204,
            404,
        }

    with Session(engine) as session:
        session.execute(
            delete(UserSession).where(
                UserSession.user_id == user["id"]
            )
        )

        session.execute(
            delete(AuthIdentity).where(
                AuthIdentity.user_id == user["id"]
            )
        )

        session.execute(
            delete(User).where(
                User.id == user["id"]
            )
        )

        session.commit()


def test_authenticated_user_cannot_access_another_users_resources():
    app = _build_app()
    client = TestClient(app)

    user_a = _register_user(
        client,
        "a",
    )
    user_b = _register_user(
        client,
        "b",
    )

    user_a_headers = _headers(
        user_a["access_token"]
    )
    user_b_headers = _headers(
        user_b["access_token"]
    )

    resource_ids: dict[str, int | None | bool] = {
        "task_id": None,
        "reminder_id": None,
        "conversation_id": None,
        "permission_tool_create": False,
        "destination_id": None,
    }

    try:
        task_response = client.post(
            "/tasks",
            headers=user_a_headers,
            json={
                "title": "User A private task",
            },
        )
        assert task_response.status_code == 201
        resource_ids["task_id"] = (
            task_response.json()["id"]
        )

        reminder_response = client.post(
            "/reminders",
            headers=user_a_headers,
            json={
                "title": "User A private reminder",
                "reminder_time": (
                    "2030-01-01T12:00:00"
                ),
            },
        )
        assert reminder_response.status_code == 201
        resource_ids["reminder_id"] = (
            reminder_response.json()["id"]
        )

        conversation_response = client.post(
            "/conversations",
            headers=user_a_headers,
            json={
                "title": "User A private conversation",
            },
        )
        assert conversation_response.status_code == 201
        resource_ids["conversation_id"] = (
            conversation_response.json()["id"]
        )

        permission_response = client.put(
            "/permissions/task/create",
            headers=user_a_headers,
            json={
                "mode": "allow",
            },
        )
        assert permission_response.status_code == 200
        resource_ids["permission_tool_create"] = True

        destination_response = client.post(
            "/notification-destinations",
            headers=user_a_headers,
            json={
                "channel": "email",
                "destination": (
                    "user-a@example.test"
                ),
                "label": "User A only",
            },
        )
        assert destination_response.status_code == 201
        resource_ids["destination_id"] = (
            destination_response.json()["id"]
        )

        task_id = resource_ids["task_id"]
        reminder_id = resource_ids["reminder_id"]
        conversation_id = resource_ids[
            "conversation_id"
        ]
        destination_id = resource_ids[
            "destination_id"
        ]

        tasks_for_b = client.get(
            "/tasks",
            headers=user_b_headers,
        )
        assert tasks_for_b.status_code == 200
        assert all(
            item["id"] != task_id
            for item in tasks_for_b.json()
        )

        task_update_for_b = client.patch(
            f"/tasks/{task_id}",
            headers=user_b_headers,
            json={
                "priority": "high",
            },
        )
        assert task_update_for_b.status_code == 404

        task_delete_for_b = client.delete(
            f"/tasks/{task_id}",
            headers=user_b_headers,
        )
        assert task_delete_for_b.status_code == 404

        reminders_for_b = client.get(
            "/reminders",
            headers=user_b_headers,
        )
        assert reminders_for_b.status_code == 200
        assert all(
            item["id"] != reminder_id
            for item in reminders_for_b.json()
        )

        reminder_update_for_b = client.patch(
            f"/reminders/{reminder_id}",
            headers=user_b_headers,
            json={
                "title": "Attempted takeover",
            },
        )
        assert reminder_update_for_b.status_code == 404

        reminder_delete_for_b = client.delete(
            f"/reminders/{reminder_id}",
            headers=user_b_headers,
        )
        assert reminder_delete_for_b.status_code == 404

        conversations_for_b = client.get(
            "/conversations",
            headers=user_b_headers,
        )
        assert conversations_for_b.status_code == 200
        assert all(
            item["id"] != conversation_id
            for item in conversations_for_b.json()
        )

        messages_for_b = client.get(
            f"/conversations/{conversation_id}/messages",
            headers=user_b_headers,
        )
        assert messages_for_b.status_code == 200
        assert messages_for_b.json()["messages"] == []

        state_for_b = client.get(
            f"/conversations/{conversation_id}/state",
            headers=user_b_headers,
        )
        assert state_for_b.status_code == 200
        assert state_for_b.json()["state"] == "unknown"

        conversation_update_for_b = client.patch(
            f"/conversations/{conversation_id}",
            headers=user_b_headers,
            json={
                "title": "Attempted takeover",
            },
        )
        assert conversation_update_for_b.status_code == 404

        conversation_delete_for_b = client.delete(
            f"/conversations/{conversation_id}",
            headers=user_b_headers,
        )
        assert conversation_delete_for_b.status_code == 404

        permissions_for_b = client.get(
            "/permissions",
            headers=user_b_headers,
        )
        assert permissions_for_b.status_code == 200
        assert not any(
            permission["tool"] == "task"
            and permission["action"] == "create"
            for permission in permissions_for_b.json()
        )

        permission_delete_for_b = client.delete(
            "/permissions/task/create",
            headers=user_b_headers,
        )
        assert permission_delete_for_b.status_code == 404

        destinations_for_b = client.get(
            "/notification-destinations",
            headers=user_b_headers,
        )
        assert destinations_for_b.status_code == 200
        assert all(
            item["id"] != destination_id
            for item in destinations_for_b.json()
        )

        destination_default_for_b = client.post(
            f"/notification-destinations/{destination_id}/default",
            headers=user_b_headers,
        )
        assert destination_default_for_b.status_code == 404

        destination_delete_for_b = client.delete(
            f"/notification-destinations/{destination_id}",
            headers=user_b_headers,
        )
        assert destination_delete_for_b.status_code == 404

        # Prove that user B remains the owner of newly-created data
        # rather than inheriting or overriding user A's identity.
        user_b_task = client.post(
            "/tasks",
            headers=user_b_headers,
            json={
                "title": "User B own task",
            },
        )
        assert user_b_task.status_code == 201

        user_b_task_id = user_b_task.json()["id"]

        tasks_for_b_after_own_create = client.get(
            "/tasks",
            headers=user_b_headers,
        )
        assert tasks_for_b_after_own_create.status_code == 200
        assert any(
            item["id"] == user_b_task_id
            for item in tasks_for_b_after_own_create.json()
        )

        user_a_cannot_see_user_b_task = client.patch(
            f"/tasks/{user_b_task_id}",
            headers=user_a_headers,
            json={
                "priority": "high",
            },
        )
        assert user_a_cannot_see_user_b_task.status_code == 404

        response = client.delete(
            f"/tasks/{user_b_task_id}",
            headers=user_b_headers,
        )
        assert response.status_code == 204

    finally:
        _cleanup_user(
            client,
            user_a,
            resource_ids,
        )
        _cleanup_user(
            client,
            user_b,
            {
                "task_id": None,
                "reminder_id": None,
                "conversation_id": None,
                "permission_tool_create": False,
                "destination_id": None,
            },
        )
