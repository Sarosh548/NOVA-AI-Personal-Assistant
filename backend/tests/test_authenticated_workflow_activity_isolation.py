from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from api.activity import router as activity_router
from api.auth import get_token_service, router as auth_router
from api.workflows import router as workflow_router
from config import Settings
from database.connection import engine
from models.activity_event import ActivityEvent
from models.auth_identity import AuthIdentity
from models.user import User
from models.user_session import UserSession
from models.workflow import Workflow
from models.workflow_step import WorkflowStep
from services.token_service import TokenService


PASSWORD = "CorrectPassword123!"
TEST_SECRET = (
    "workflow-activity-isolation-test-secret-key-longer-than-32"
)


def _now() -> datetime:
    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(workflow_router)
    app.include_router(activity_router)

    token_service = TokenService(
        settings=Settings(
            auth_jwt_secret_key=TEST_SECRET,
            auth_jwt_algorithm="HS256",
            auth_jwt_issuer="nova-api-test",
            auth_jwt_audience="nova-client-test",
            auth_access_token_expire_minutes=10,
        )
    )

    app.dependency_overrides[
        get_token_service
    ] = lambda: token_service

    return app


def _register_user(
    client: TestClient,
    label: str,
) -> dict[str, str]:
    identifier = (
        f"workflow-activity-{label}-"
        f"{uuid4().hex[:12]}@example.test"
    )

    response = client.post(
        "/auth/register",
        json={
            "identifier": identifier,
            "password": PASSWORD,
            "display_name": f"Workflow Activity {label}",
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


def _seed_workflow(
    user_id: str,
) -> int:
    now = _now()

    workflow = Workflow(
        user_id=user_id,
        conversation_id=None,
        status="pending",
        execution_mode="autonomous",
        scheduled_at=now,
        plan={
            "goal": "User-owned autonomous workflow",
        },
        result=None,
        error=None,
        idempotency_key=(
            f"test-{uuid4().hex}"
        ),
        claim_token=None,
        lease_until=None,
        heartbeat_at=None,
        created_at=now,
        updated_at=now,
        started_at=None,
        completed_at=None,
    )

    with Session(engine) as session:
        session.add(workflow)
        session.flush()

        session.add(
            WorkflowStep(
                workflow_id=workflow.id,
                step_id="step-1",
                position=0,
                tool="task",
                action="create",
                data={
                    "title": "Private workflow step",
                },
                depends_on=[],
                status="pending",
                result=None,
                error=None,
                attempts=0,
                created_at=now,
                updated_at=now,
                started_at=None,
                completed_at=None,
            )
        )

        workflow_id = workflow.id
        session.commit()

    return workflow_id


def _seed_activity_event(
    user_id: str,
    workflow_id: int,
) -> int:
    event = ActivityEvent(
        user_id=user_id,
        conversation_id=None,
        workflow_id=workflow_id,
        event_type="workflow.completed",
        source="workflow",
        status="success",
        title="Private workflow activity",
        summary="User-owned workflow activity event.",
        event_metadata={
            "private": True,
        },
        created_at=_now(),
    )

    with Session(engine) as session:
        session.add(event)
        session.flush()
        event_id = event.id
        session.commit()

    return event_id


def _cleanup_user(
    user_id: str,
) -> None:
    with Session(engine) as session:
        session.execute(
            delete(ActivityEvent).where(
                ActivityEvent.user_id == user_id
            )
        )
        session.execute(
            delete(WorkflowStep).where(
                WorkflowStep.workflow_id.in_(
                    session.query(Workflow.id).where(
                        Workflow.user_id == user_id
                    )
                )
            )
        )
        session.execute(
            delete(Workflow).where(
                Workflow.user_id == user_id
            )
        )
        session.execute(
            delete(UserSession).where(
                UserSession.user_id == user_id
            )
        )
        session.execute(
            delete(AuthIdentity).where(
                AuthIdentity.user_id == user_id
            )
        )
        session.execute(
            delete(User).where(
                User.id == user_id
            )
        )
        session.commit()


def test_authenticated_users_are_isolated_for_workflows_and_activity():
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

    try:
        workflow_a = _seed_workflow(
            user_a["id"]
        )
        workflow_b = _seed_workflow(
            user_b["id"]
        )

        activity_a = _seed_activity_event(
            user_a["id"],
            workflow_a,
        )
        activity_b = _seed_activity_event(
            user_b["id"],
            workflow_b,
        )

        headers_a = _headers(
            user_a["access_token"]
        )
        headers_b = _headers(
            user_b["access_token"]
        )

        workflows_b = client.get(
            "/workflows",
            headers=headers_b,
        )
        assert workflows_b.status_code == 200
        workflow_ids_b = {
            item["id"]
            for item in workflows_b.json()
        }
        assert workflow_b in workflow_ids_b
        assert workflow_a not in workflow_ids_b

        workflow_a_for_b = client.get(
            f"/workflows/{workflow_a}",
            headers=headers_b,
        )
        assert workflow_a_for_b.status_code == 404

        workflow_cancel_for_b = client.post(
            f"/workflows/{workflow_a}/cancel",
            headers=headers_b,
        )
        assert workflow_cancel_for_b.status_code == 404

        workflow_a_for_a = client.get(
            f"/workflows/{workflow_a}",
            headers=headers_a,
        )
        assert workflow_a_for_a.status_code == 200
        assert workflow_a_for_a.json()["id"] == workflow_a
        assert workflow_a_for_a.json()["steps"][0]["tool"] == "task"

        workflow_cancel_for_a = client.post(
            f"/workflows/{workflow_a}/cancel",
            headers=headers_a,
        )
        assert workflow_cancel_for_a.status_code == 200
        assert workflow_cancel_for_a.json() == {
            "action": "cancel",
            "updated": True,
        }

        workflows_a_after_cancel = client.get(
            "/workflows",
            headers=headers_a,
        )
        assert workflows_a_after_cancel.status_code == 200
        workflow_a_payload = next(
            item
            for item in workflows_a_after_cancel.json()
            if item["id"] == workflow_a
        )
        assert workflow_a_payload["status"] == "cancelled"

        activity_b = client.get(
            "/activity",
            headers=headers_b,
        )
        assert activity_b.status_code == 200
        activity_ids_b = {
            item["id"]
            for item in activity_b.json()
        }
        activity_workflow_ids_b = {
            item["workflow_id"]
            for item in activity_b.json()
        }
        assert activity_b in activity_ids_b
        assert activity_a not in activity_ids_b
        assert workflow_b in activity_workflow_ids_b
        assert workflow_a not in activity_workflow_ids_b

        activity_a_for_a = client.get(
            "/activity",
            headers=headers_a,
        )
        assert activity_a_for_a.status_code == 200
        activity_ids_a = {
            item["id"]
            for item in activity_a_for_a.json()
        }
        assert activity_a in activity_ids_a
        assert activity_b not in activity_ids_a

    finally:
        _cleanup_user(
            user_a["id"]
        )
        _cleanup_user(
            user_b["id"]
        )
