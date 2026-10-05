from __future__ import annotations

from uuid import uuid4
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from api.auth import (
    get_auth_service,
    get_password_reset_service,
    get_token_service,
    get_user_service,
    router,
)
from config import Settings
from database.connection import engine
from models.auth_identity import AuthIdentity
from models.password_reset_challenge import PasswordResetChallenge
from models.user import User
from models.user_session import UserSession
from services.auth_service import AuthService
from services.password_reset_service import PasswordResetService
from services.token_service import TokenService
from services.user_service import UserService


TEST_SECRET = "password-reset-api-test-secret-key-that-is-longer-than-32-characters"


class FakeEmailNotificationService:
    def __init__(self):
        self.messages = []

    def send_email(
        self,
        *,
        user_id: str,
        to,
        subject: str,
        body: str,
        cc=None,
        bcc=None,
    ) -> bool:
        self.messages.append(
            {
                "user_id": user_id,
                "to": to,
                "subject": subject,
                "body": body,
            }
        )
        return True


def _cleanup_user(user_id: str) -> None:
    with Session(engine) as session:
        session.execute(
            delete(PasswordResetChallenge).where(
                PasswordResetChallenge.user_id == user_id
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
            delete(User).where(User.id == user_id)
        )
        session.commit()


def test_request_password_reset_is_generic_for_unknown_email(
    monkeypatch,
):
    notifications = FakeEmailNotificationService()
    service = PasswordResetService(
        notification_service=notifications,
        engine=engine,
        secret_key=TEST_SECRET,
    )

    settings = Settings(
        auth_jwt_secret_key=TEST_SECRET,
        auth_jwt_algorithm="HS256",
        auth_jwt_issuer="nova-api-test",
        auth_jwt_audience="nova-client-test",
        auth_access_token_expire_minutes=10,
    )

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_password_reset_service] = lambda: service

    client = TestClient(app)

    monkeypatch.setattr(
        PasswordResetService,
        "_generate_code",
        classmethod(lambda cls: "123456"),
    )

    response = client.post(
        "/auth/request-password-reset",
        json={"email": f"missing-{uuid4().hex[:12]}@example.test"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == (
        "If an account exists for that email, "
        "a password reset code has been sent."
    )
    assert notifications.messages == []

    app.dependency_overrides.clear()


def test_request_and_reset_password_then_sign_in_with_new_password(
    monkeypatch,
):
    notifications = FakeEmailNotificationService()
    reset_service = PasswordResetService(
        notification_service=notifications,
        engine=engine,
        secret_key=TEST_SECRET,
    )
    auth_service = AuthService(engine=engine)
    token_service = TokenService(
        settings=Settings(
            auth_jwt_secret_key=TEST_SECRET,
            auth_jwt_algorithm="HS256",
            auth_jwt_issuer="nova-api-test",
            auth_jwt_audience="nova-client-test",
            auth_access_token_expire_minutes=10,
        )
    )
    user_service = UserService(engine=engine)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_password_reset_service] = lambda: reset_service
    app.dependency_overrides[get_token_service] = lambda: token_service
    app.dependency_overrides[get_user_service] = lambda: user_service

    client = TestClient(app)

    monkeypatch.setattr(
        PasswordResetService,
        "_generate_code",
        classmethod(lambda cls: "654321"),
    )

    identifier = f"reset-api-{uuid4().hex[:12]}@example.test"
    user, _identity = auth_service.register_password_user(
        identifier=identifier,
        password="OldPassword123!",
        display_name="Reset API User",
    )

    try:
        request_response = client.post(
            "/auth/request-password-reset",
            json={"email": identifier},
        )
        assert request_response.status_code == 200
        assert len(notifications.messages) == 1
        assert "654321" in notifications.messages[0]["body"]

        reset_response = client.post(
            "/auth/reset-password",
            json={
                "email": identifier,
                "code": "654321",
                "new_password": "NewPassword123!",
            },
        )

        assert reset_response.status_code == 200
        assert reset_response.json()["id"] == user.id

        old_login = client.post(
            "/auth/login",
            data={
                "grant_type": "password",
                "username": identifier,
                "password": "OldPassword123!",
            },
        )
        assert old_login.status_code == 401

        new_login = client.post(
            "/auth/login",
            data={
                "grant_type": "password",
                "username": identifier,
                "password": "NewPassword123!",
            },
        )
        assert new_login.status_code == 200
        assert new_login.json()["user"]["id"] == user.id
    finally:
        _cleanup_user(user.id)
        app.dependency_overrides.clear()
