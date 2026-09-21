from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from models.audit_event import AuditEvent
from models.user import User
from services.audit_service import AuditService
from services.request_context import set_request_id, reset_request_id


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
    AuditEvent.__table__.create(
        bind=db_engine
    )

    return db_engine


def teardown_runtime(
    db_engine,
):
    AuditEvent.__table__.drop(
        bind=db_engine
    )
    User.__table__.drop(
        bind=db_engine
    )
    db_engine.dispose()


def test_audit_event_is_persisted_with_request_context():
    db_engine = build_runtime()

    try:
        user_id = str(uuid4())
        now = datetime(
            2026,
            9,
            21,
            10,
            0,
            tzinfo=timezone.utc,
        )

        with Session(db_engine) as session:
            session.add(
                User(
                    id=user_id,
                    display_name="Audit User",
                    is_active=True,
                    created_at=now.replace(
                        tzinfo=None
                    ),
                    updated_at=now.replace(
                        tzinfo=None
                    ),
                )
            )
            session.commit()

        service = AuditService(
            db_engine=db_engine
        )

        token = set_request_id(
            "audit-request-123"
        )

        try:
            result = service.record_event(
                event_type="authentication",
                action="login",
                status="success",
                user_id=user_id,
                resource_type="session",
                resource_id="session-123",
                metadata={
                    "safe": True
                },
            )
        finally:
            reset_request_id(token)

        assert result["user_id"] == user_id
        assert result["request_id"] == "audit-request-123"
        assert result["action"] == "login"
        assert result["status"] == "success"

        with Session(db_engine) as session:
            event = session.get(
                AuditEvent,
                result["id"],
            )

            assert event is not None
            assert event.event_type == "authentication"
            assert event.request_id == "audit-request-123"
            assert event.event_metadata == {
                "safe": True
            }

    finally:
        teardown_runtime(
            db_engine
        )


def test_audit_event_rejects_invalid_status():
    db_engine = build_runtime()

    try:
        service = AuditService(
            db_engine=db_engine
        )

        try:
            service.record_event(
                event_type="authentication",
                action="login",
                status="invalid",
            )
            raise AssertionError(
                "Expected ValueError."
            )
        except ValueError as exc:
            assert str(exc) == (
                "Invalid audit event status."
            )
    finally:
        teardown_runtime(
            db_engine
        )
