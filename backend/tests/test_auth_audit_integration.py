from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import api.auth as auth_module
from api.auth import (
    get_auth_service,
    get_token_service,
    get_user_service,
    router as auth_router,
)
from config import Settings
from models.audit_event import AuditEvent
from models.auth_identity import AuthIdentity
from models.user import User
from models.user_session import UserSession
from services.audit_service import AuditService
from services.auth_service import AuthService
from services.token_service import TokenService
from services.user_service import UserService


TEST_SECRET = (
    "audit-integration-test-secret-key-longer-than-32"
)


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
    AuthIdentity.__table__.create(
        bind=db_engine
    )
    UserSession.__table__.create(
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
    UserSession.__table__.drop(
        bind=db_engine
    )
    AuthIdentity.__table__.drop(
        bind=db_engine
    )
    User.__table__.drop(
        bind=db_engine
    )
    db_engine.dispose()


def test_authentication_lifecycle_writes_audit_events(
    monkeypatch,
):
    db_engine = build_runtime()

    try:
        settings = Settings(
            auth_jwt_secret_key=TEST_SECRET,
            auth_jwt_algorithm="HS256",
            auth_jwt_issuer="nova-api-test",
            auth_jwt_audience="nova-client-test",
            auth_access_token_expire_minutes=10,
        )

        auth_service = AuthService(
            engine=db_engine
        )
        token_service = TokenService(
            settings=settings
        )
        user_service = UserService(
            engine=db_engine
        )

        audit_service = AuditService(
            db_engine=db_engine
        )

        monkeypatch.setattr(
            auth_module,
            "audit_service",
            audit_service,
        )

        app = FastAPI()
        app.include_router(
            auth_router
        )

        app.dependency_overrides[
            get_auth_service
        ] = lambda: auth_service

        app.dependency_overrides[
            get_token_service
        ] = lambda: token_service

        app.dependency_overrides[
            get_user_service
        ] = lambda: user_service

        client = TestClient(app)

        identifier = (
            f"audit-{uuid4().hex[:12]}"
            "@example.test"
        )

        register = client.post(
            "/auth/register",
            json={
                "identifier": identifier,
                "password": "CorrectPassword123!",
            },
            headers={
                "X-Request-ID": "audit-register-request"
            },
        )

        assert register.status_code == 201

        body = register.json()
        user_id = body["user"]["id"]

        login = client.post(
            "/auth/login",
            data={
                "grant_type": "password",
                "username": identifier,
                "password": "CorrectPassword123!",
            },
            headers={
                "X-Request-ID": "audit-login-request"
            },
        )

        assert login.status_code == 200

        logout = client.post(
            "/auth/logout",
            headers={
                "Authorization": (
                    f"Bearer {login.json()['access_token']}"
                ),
                "X-Request-ID": "audit-logout-request",
            },
        )

        assert logout.status_code == 204

        with Session(db_engine) as session:
            events = session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.user_id == user_id
                )
                .order_by(
                    AuditEvent.id.asc()
                )
            ).all()

        assert [
            (
                event.action,
                event.status,
                event.request_id,
            )
            for event in events
        ] == [
            (
                "register",
                "success",
                "audit-register-request",
            ),
            (
                "login",
                "success",
                "audit-login-request",
            ),
            (
                "logout",
                "success",
                "audit-logout-request",
            ),
        ]

    finally:
        teardown_runtime(
            db_engine
        )
