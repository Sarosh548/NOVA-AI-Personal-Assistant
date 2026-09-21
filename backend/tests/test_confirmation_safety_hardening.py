from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

import services.confirmation_service as confirmation_module
from models.audit_event import AuditEvent
from models.confirmation import Confirmation
from database.connection import engine as default_engine
from models.user import User
from services.audit_service import AuditService
from api.auth import (
    get_current_auth_context,
)
from api.confirmations import (
    get_confirmation_service,
    router as confirmation_router,
)
from api.auth import AuthenticatedContext
from services.confirmation_execution_service import (
    ConfirmationExecutionService,
)
from services.permission_service import PermissionDecision
from services.permission_service import PermissionService


def build_runtime():
    db_engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    User.__table__.create(
        bind=db_engine
    )
    Confirmation.__table__.create(
        bind=db_engine
    )
    AuditEvent.__table__.create(
        bind=db_engine
    )

    confirmation_module.engine = db_engine
    confirmation_module.audit_service = AuditService(
        db_engine=db_engine
    )

    return db_engine


def teardown_runtime(db_engine):
    AuditEvent.__table__.drop(
        bind=db_engine
    )
    Confirmation.__table__.drop(
        bind=db_engine
    )
    User.__table__.drop(
        bind=db_engine
    )
    db_engine.dispose()
    confirmation_module.engine = default_engine
    confirmation_module.audit_service = None


def test_approval_claim_creates_execution_lease_and_token(
    monkeypatch,
):
    db_engine = build_runtime()

    try:
        service = confirmation_module.ConfirmationService()

        confirmation_id = service.create_confirmation(
            user_id="lease-user",
            conversation_id=None,
            tool="task",
            action="create",
            data={"title": "Test"},
            reason="Create task?",
        )

        claimed = service.approve_and_claim_confirmation(
            user_id="lease-user",
            confirmation_id=confirmation_id,
            lease_seconds=120,
        )

        assert claimed is not None
        assert claimed["status"] == "processing"
        assert isinstance(
            claimed["claim_token"],
            str,
        )
        assert len(claimed["claim_token"]) == 32
        assert claimed["lease_until"] is not None
        assert claimed["attempt_count"] == 1

        public = service.get_confirmation(
            user_id="lease-user",
            confirmation_id=confirmation_id,
        )

        assert public is not None
        assert "claim_token" not in public

    finally:
        teardown_runtime(db_engine)


def test_expired_processing_confirmation_is_reclaimed_once():
    db_engine = build_runtime()

    try:
        service = confirmation_module.ConfirmationService()
        now = service._utc_now_naive()

        confirmation = Confirmation(
            user_id="lease-user",
            conversation_id=None,
            tool="task",
            action="create",
            data={"title": "Test"},
            reason="Create task?",
            status="processing",
            created_at=now - timedelta(minutes=10),
            expires_at=now + timedelta(minutes=5),
            resolved_at=now - timedelta(minutes=10),
            claim_token="old-claim-token",
            lease_until=now - timedelta(seconds=1),
            attempt_count=1,
        )

        with confirmation_module.Session(
            db_engine
        ) as session:
            session.add(confirmation)
            session.commit()
            session.refresh(confirmation)
            confirmation_id = confirmation.id

        reclaimed = service.claim_confirmation(
            user_id="lease-user",
            confirmation_id=confirmation_id,
            lease_seconds=120,
        )

        assert reclaimed is not None
        assert reclaimed["status"] == "processing"
        assert reclaimed["claim_token"] != "old-claim-token"
        assert reclaimed["attempt_count"] == 2

        active_retry = service.claim_confirmation(
            user_id="lease-user",
            confirmation_id=confirmation_id,
            lease_seconds=120,
        )

        assert active_retry is None

    finally:
        teardown_runtime(db_engine)


def test_expired_approved_confirmation_cannot_be_reclaimed():
    db_engine = build_runtime()

    try:
        service = confirmation_module.ConfirmationService()
        now = service._utc_now_naive()

        confirmation = Confirmation(
            user_id="lease-user",
            conversation_id=None,
            tool="task",
            action="create",
            data={"title": "Expired"},
            reason="Create task?",
            status="approved",
            created_at=now - timedelta(minutes=10),
            expires_at=now - timedelta(seconds=1),
            resolved_at=now - timedelta(minutes=9),
            claim_token=None,
            lease_until=None,
            attempt_count=1,
        )

        with confirmation_module.Session(
            db_engine
        ) as session:
            session.add(confirmation)
            session.commit()
            session.refresh(confirmation)
            confirmation_id = confirmation.id

        claimed = service.claim_confirmation(
            user_id="lease-user",
            confirmation_id=confirmation_id,
            lease_seconds=120,
        )

        assert claimed is None

        stored = service.get_confirmation(
            user_id="lease-user",
            confirmation_id=confirmation_id,
        )

        assert stored is not None
        assert stored["status"] == "expired"
        assert "claim_token" not in stored

    finally:
        teardown_runtime(db_engine)


def test_stale_worker_cannot_finalize_reclaimed_confirmation():
    db_engine = build_runtime()

    try:
        service = confirmation_module.ConfirmationService()
        now = service._utc_now_naive()

        confirmation = Confirmation(
            user_id="lease-user",
            conversation_id=None,
            tool="task",
            action="create",
            data={"title": "Test"},
            reason="Create task?",
            status="approved",
            created_at=now,
            expires_at=now + timedelta(minutes=5),
            resolved_at=now,
            claim_token=None,
            lease_until=None,
            attempt_count=0,
        )

        with confirmation_module.Session(
            db_engine
        ) as session:
            session.add(confirmation)
            session.commit()
            session.refresh(confirmation)
            confirmation_id = confirmation.id

        first = service.claim_confirmation(
            user_id="lease-user",
            confirmation_id=confirmation_id,
            lease_seconds=1,
        )

        assert first is not None

        with confirmation_module.Session(
            db_engine
        ) as session:
            stored = session.scalar(
                select(Confirmation).where(
                    Confirmation.id == confirmation_id
                )
            )
            assert stored is not None
            stored.lease_until = now - timedelta(
                seconds=1
            )
            session.commit()

        second = service.claim_confirmation(
            user_id="lease-user",
            confirmation_id=confirmation_id,
            lease_seconds=120,
        )

        assert second is not None
        assert second["claim_token"] != first["claim_token"]
        assert second["attempt_count"] == 2

        stale_finish = service.finish_confirmation(
            user_id="lease-user",
            confirmation_id=confirmation_id,
            success=True,
            claim_token=first["claim_token"],
        )

        assert stale_finish is None

        current_finish = service.finish_confirmation(
            user_id="lease-user",
            confirmation_id=confirmation_id,
            success=True,
            claim_token=second["claim_token"],
        )

        assert current_finish is not None
        assert current_finish["status"] == "consumed"

    finally:
        teardown_runtime(db_engine)


class OwnershipConfirmationService:
    def get_confirmation(
        self,
        *,
        user_id,
        confirmation_id,
    ):
        if user_id != "owner-user":
            return None

        return {
            "id": confirmation_id,
            "user_id": "owner-user",
            "conversation_id": None,
            "tool": "task",
            "action": "create",
            "data": {},
            "reason": "Create task?",
            "status": "pending",
            "created_at": datetime(
                2026,
                9,
                21,
                10,
                0,
            ),
            "expires_at": datetime(
                2026,
                9,
                21,
                10,
                5,
            ),
            "resolved_at": None,
            "lease_until": None,
            "attempt_count": 0,
        }


def test_confirmation_api_cannot_cross_user_boundary():
    app = FastAPI()
    app.include_router(confirmation_router)

    now = datetime.now().astimezone().replace(
        tzinfo=None
    )

    context = AuthenticatedContext(
        user=type(
            "FakeUser",
            (),
            {
                "id": "attacker-user",
                "is_active": True,
            },
        )(),
        session=type(
            "FakeSession",
            (),
            {
                "id": "attacker-session",
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
        get_confirmation_service
    ] = lambda: OwnershipConfirmationService()

    client = TestClient(app)

    response = client.get(
        "/confirmations/42"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "Confirmation not found."
    )


def test_confirmation_lifecycle_writes_audit_events():
    db_engine = build_runtime()

    try:
        service = confirmation_module.ConfirmationService()

        confirmation_id = service.create_confirmation(
            user_id="audit-user",
            conversation_id=7,
            tool="task",
            action="create",
            data={"title": "Audit task"},
            reason="Create task?",
        )

        approved = service.approve_confirmation(
            user_id="audit-user",
            confirmation_id=confirmation_id,
        )
        assert approved is not None
        assert approved["status"] == "approved"

        claimed = service.claim_confirmation(
            user_id="audit-user",
            confirmation_id=confirmation_id,
        )
        assert claimed is not None

        finished = service.finish_confirmation(
            user_id="audit-user",
            confirmation_id=confirmation_id,
            success=True,
            claim_token=claimed["claim_token"],
        )
        assert finished is not None

        with confirmation_module.Session(
            db_engine
        ) as session:
            events = session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.user_id == "audit-user",
                )
                .order_by(AuditEvent.id.asc())
            ).all()

        assert [
            (event.event_type, event.action, event.status)
            for event in events
        ] == [
            ("confirmation", "create", "success"),
            ("confirmation", "approve", "success"),
            ("confirmation", "claim", "success"),
            ("confirmation", "finish", "success"),
        ]

    finally:
        teardown_runtime(db_engine)


class DenyPermissionService:
    def check(
        self,
        *,
        user_id,
        tool,
        action,
        user_requested,
        data,
    ):
        return PermissionDecision(
            allowed=False,
            requires_confirmation=False,
            reason="Permission was revoked.",
            risk_level="medium",
            risk_flags=(),
        )


class FakeConfirmationService:
    def __init__(self):
        self.finish_calls = []

    def claim_confirmation(
        self,
        *,
        user_id,
        confirmation_id,
    ):
        return {
            "id": confirmation_id,
            "user_id": user_id,
            "conversation_id": None,
            "tool": "task",
            "action": "create",
            "data": {
                "title": "Protected task",
            },
            "reason": "Create task?",
            "status": "processing",
            "created_at": datetime(
                2026,
                9,
                21,
                10,
                0,
            ),
            "expires_at": datetime(
                2026,
                9,
                21,
                10,
                5,
            ),
            "resolved_at": None,
            "claim_token": "claim-token",
            "lease_until": datetime(
                2026,
                9,
                21,
                10,
                15,
            ),
            "attempt_count": 1,
        }

    def finish_confirmation(
        self,
        *,
        user_id,
        confirmation_id,
        success,
        claim_token,
    ):
        self.finish_calls.append(
            {
                "user_id": user_id,
                "confirmation_id": confirmation_id,
                "success": success,
                "claim_token": claim_token,
            }
        )
        return {
            "id": confirmation_id,
            "status": "failed",
            "claim_token": claim_token,
        }


class CountingToolRouter:
    def __init__(self):
        self.calls = []

    def execute(
        self,
        *,
        intent,
        user_id,
        data,
    ):
        self.calls.append(
            {
                "intent": intent,
                "user_id": user_id,
                "data": data,
            }
        )
        return {
            "success": True,
            "tool": intent,
            "action": "create",
            "result": {"id": 1},
            "error": None,
        }


def test_confirmed_execution_rechecks_current_authorization():
    confirmation_service = FakeConfirmationService()
    tool_router = CountingToolRouter()

    service = ConfirmationExecutionService(
        confirmation_service=confirmation_service,
        tool_router=tool_router,
        permission_service=DenyPermissionService(),
    )

    result = service.execute_approved_confirmation(
        user_id="user-001",
        confirmation_id=101,
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == (
        "The action is no longer permitted under "
        "the current authorization policy."
    )
    assert tool_router.calls == []
    assert confirmation_service.finish_calls == [
        {
            "user_id": "user-001",
            "confirmation_id": 101,
            "success": False,
            "claim_token": "claim-token",
        }
    ]
