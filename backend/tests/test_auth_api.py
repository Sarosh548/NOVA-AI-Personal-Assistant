from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.auth import (
    get_auth_service,
    get_email_verification_service,
    get_token_service,
    get_user_service,
    router,
)
from api.schemas.auth import UserResponse
from config import Settings
from database.connection import engine
from models.auth_identity import AuthIdentity
from models.user import User
from models.user_session import UserSession
from services.auth_service import AuthService
from services.email_verification_service import (
    EmailVerificationService,
)
from services.token_service import TokenService
from services.user_service import UserService


TEST_SECRET = (
    "api-test-secret-key-that-is-longer-than-32-characters"
)


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


@pytest.fixture
def api_context():
    settings = Settings(
        auth_jwt_secret_key=TEST_SECRET,
        auth_jwt_algorithm="HS256",
        auth_jwt_issuer="nova-api-test",
        auth_jwt_audience="nova-client-test",
        auth_access_token_expire_minutes=10,
    )

    auth_service = AuthService(
        engine=engine
    )

    token_service = TokenService(
        settings=settings
    )

    user_service = UserService(
        engine=engine
    )

    notification_service = (
        FakeEmailNotificationService()
    )
    verification_service = (
        EmailVerificationService(
            notification_service=notification_service,
            engine=engine,
            secret_key=TEST_SECRET,
        )
    )

    app = FastAPI()
    app.include_router(router)

    app.dependency_overrides[
        get_auth_service
    ] = lambda: auth_service

    app.dependency_overrides[
        get_token_service
    ] = lambda: token_service

    app.dependency_overrides[
        get_user_service
    ] = lambda: user_service

    app.dependency_overrides[
        get_email_verification_service
    ] = lambda: verification_service

    client = TestClient(app)

    try:
        yield client, auth_service, token_service
    finally:
        app.dependency_overrides.clear()


def _mark_email_verified(user_id: str) -> None:
    with Session(engine) as session:
        user = session.get(User, user_id)
        assert user is not None
        from datetime import datetime, timezone

        user.email_verified_at = (
            datetime.now(timezone.utc).replace(tzinfo=None)
        )
        session.commit()


def _cleanup_user(user_id: str) -> None:
    with Session(engine) as session:
        session.execute(
            delete(UserSession)
            .where(
                UserSession.user_id == user_id
            )
        )

        session.execute(
            delete(AuthIdentity)
            .where(
                AuthIdentity.user_id == user_id
            )
        )

        session.execute(
            delete(User)
            .where(
                User.id == user_id
            )
        )

        session.commit()


def _unique_identifier() -> str:
    return (
        f"api-{uuid4().hex[:12]}"
        "@example.test"
    )


def _user_id_for_email(identifier: str) -> str:
    with Session(engine) as session:
        user_id = session.query(AuthIdentity.user_id).filter(
            AuthIdentity.provider == "password",
            AuthIdentity.provider_subject == identifier,
        ).scalar()
    assert user_id is not None
    return user_id


def _login_registered_user(client, identifier: str) -> dict:
    response = client.post(
        "/auth/login",
        data={
            "grant_type": "password",
            "username": identifier,
            "password": "CorrectPassword123!",
        },
    )

    assert response.status_code == 200
    return response.json()


def test_register_creates_account_without_authenticating(
    api_context,
):
    client, _auth_service, _token_service = (
        api_context
    )

    identifier = _unique_identifier()

    response = client.post(
        "/auth/register",
        json={
            "identifier": identifier,
            "password": "CorrectPassword123!",
            "display_name": "API Test User",
        },
    )

    assert response.status_code == 202

    body = response.json()
    assert body["user"] is None
    assert body["email_verification_required"] is True
    assert body["message"] == (
        "If the address can be registered, check your inbox "
        "for verification instructions."
    )
    user_id = _user_id_for_email(identifier)

    with Session(engine) as session:
        user = session.get(User, user_id)
        assert user is not None
        assert user.display_name == "API Test User"
        assert user.is_active is True
        sessions = session.scalars(
            select(UserSession).where(UserSession.user_id == user_id)
        ).all()

    assert sessions == []
    _cleanup_user(user_id)


def test_unverified_email_cannot_sign_in(
    api_context,
):
    client, _auth_service, _token_service = (
        api_context
    )

    identifier = _unique_identifier()

    response = client.post(
        "/auth/register",
        json={
            "identifier": identifier,
            "password": "CorrectPassword123!",
        },
    )

    assert response.status_code == 202
    user_id = _user_id_for_email(identifier)

    try:
        login_response = client.post(
            "/auth/login",
            data={
                "grant_type": "password",
                "username": identifier,
                "password": "CorrectPassword123!",
            },
        )

        assert login_response.status_code == 401
        assert login_response.json()["detail"] == (
            "Incorrect username or password."
        )

        unknown_login_response = client.post(
            "/auth/login",
            data={
                "grant_type": "password",
                "username": _unique_identifier(),
                "password": "CorrectPassword123!",
            },
        )
        assert unknown_login_response.status_code == login_response.status_code
        assert unknown_login_response.json() == login_response.json()
    finally:
        _cleanup_user(user_id)


def test_verify_email_then_sign_in(
    api_context,
    monkeypatch,
):
    client, _auth_service, _token_service = (
        api_context
    )

    monkeypatch.setattr(
        EmailVerificationService,
        "_generate_code",
        classmethod(lambda cls: "123456"),
    )

    identifier = _unique_identifier()

    response = client.post(
        "/auth/register",
        json={
            "identifier": identifier,
            "password": "CorrectPassword123!",
            "display_name": "Verified User",
        },
    )

    assert response.status_code == 202
    user_id = _user_id_for_email(identifier)

    try:
        verify_response = client.post(
            "/auth/verify-email",
            json={
                "email": identifier,
                "code": "123456",
            },
        )

        assert verify_response.status_code == 200
        assert verify_response.json()["id"] == user_id

        login_response = client.post(
            "/auth/login",
            data={
                "grant_type": "password",
                "username": identifier,
                "password": "CorrectPassword123!",
            },
        )

        assert login_response.status_code == 200
        assert login_response.json()["user"]["id"] == user_id
    finally:
        _cleanup_user(user_id)


def test_verify_email_does_not_disclose_account_state(
    api_context,
):
    client, auth_service, _token_service = api_context
    existing_email = _unique_identifier()
    user, _identity = auth_service.register_password_user(
        identifier=existing_email,
        password="CorrectPassword123!",
    )
    try:
        wrong_code = client.post(
            "/auth/verify-email",
            json={"email": existing_email, "code": "000000"},
        )
        unknown_email = client.post(
            "/auth/verify-email",
            json={"email": _unique_identifier(), "code": "000000"},
        )

        assert wrong_code.status_code == 400
        assert unknown_email.status_code == wrong_code.status_code
        assert unknown_email.json() == wrong_code.json()
        assert wrong_code.json()["detail"] == (
            "Invalid or expired verification request."
        )
    finally:
        _cleanup_user(user.id)


def test_register_duplicate_identifier_returns_generic_acknowledgement(
    api_context,
):
    client, _auth_service, _token_service = (
        api_context
    )

    identifier = _unique_identifier()

    first = client.post(
        "/auth/register",
        json={
            "identifier": identifier,
            "password": "CorrectPassword123!",
        },
    )

    assert first.status_code == 202
    first_body = first.json()
    assert first_body["user"] is None
    user_id = _user_id_for_email(identifier)

    try:
        second = client.post(
            "/auth/register",
            json={
                "identifier": identifier,
                "password": "AnotherPassword123!",
            },
        )

        assert second.status_code == 202
        assert second.json() == first_body
    finally:
        _cleanup_user(user_id)


def test_resend_verification_does_not_disclose_account_state(
    api_context,
):
    client, auth_service, _token_service = api_context
    existing_email = _unique_identifier()
    user, _identity = auth_service.register_password_user(
        identifier=existing_email,
        password="CorrectPassword123!",
    )
    unknown_email = _unique_identifier()
    known_response = client.post(
        "/auth/resend-verification",
        json={"email": existing_email},
    )
    cooldown_response = client.post(
        "/auth/resend-verification",
        json={"email": existing_email},
    )
    unknown_response = client.post(
        "/auth/resend-verification",
        json={"email": unknown_email},
    )

    assert known_response.status_code == 200
    assert cooldown_response.status_code == 200
    assert unknown_response.status_code == 200
    assert known_response.json() == cooldown_response.json()
    assert known_response.json() == unknown_response.json()

    _cleanup_user(user.id)


def test_request_password_reset_does_not_disclose_account_or_cooldown_state(
    api_context,
):
    from api.auth import get_password_reset_service
    from services.password_reset_service import PasswordResetService

    notifications = FakeEmailNotificationService()
    reset_service = PasswordResetService(
        notification_service=notifications,
        engine=engine,
        secret_key=TEST_SECRET,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_password_reset_service] = lambda: reset_service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(engine=engine)
    client = TestClient(app)

    existing_email = _unique_identifier()
    user, _identity = AuthService(engine=engine).register_password_user(
        identifier=existing_email,
        password="CorrectPassword123!",
    )
    try:
        first = client.post(
            "/auth/request-password-reset",
            json={"email": existing_email},
        )
        second = client.post(
            "/auth/request-password-reset",
            json={"email": existing_email},
        )
        unknown = client.post(
            "/auth/request-password-reset",
            json={"email": _unique_identifier()},
        )

        assert first.status_code == second.status_code == unknown.status_code == 200
        assert first.json() == second.json() == unknown.json()
    finally:
        _cleanup_user(user.id)
        app.dependency_overrides.clear()


def test_register_short_password_is_rejected(
    api_context,
):
    client, _auth_service, _token_service = (
        api_context
    )

    response = client.post(
        "/auth/register",
        json={
            "identifier": _unique_identifier(),
            "password": "short",
        },
    )

    assert response.status_code == 422


def test_login_success(
    api_context,
):
    client, auth_service, _token_service = (
        api_context
    )

    identifier = _unique_identifier()

    user, _identity = (
        auth_service.register_password_user(
            identifier=identifier,
            password="CorrectPassword123!",
            display_name="Login User",
        )
    )
    _mark_email_verified(user.id)

    try:
        response = client.post(
            "/auth/login",
            data={
                "grant_type": "password",
                "username": identifier,
                "password": "CorrectPassword123!",
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["access_token"]
        assert body["refresh_token"]
        assert body["user"]["id"] == user.id
    finally:
        _cleanup_user(user.id)


def test_login_wrong_password_returns_401(
    api_context,
):
    client, auth_service, _token_service = (
        api_context
    )

    identifier = _unique_identifier()

    user, _identity = (
        auth_service.register_password_user(
            identifier=identifier,
            password="CorrectPassword123!",
        )
    )

    try:
        response = client.post(
            "/auth/login",
            data={
                "grant_type": "password",
                "username": identifier,
                "password": "WrongPassword123!",
            },
        )

        assert response.status_code == 401
        assert (
            response.headers["www-authenticate"]
            == "Bearer"
        )
    finally:
        _cleanup_user(user.id)


def test_login_requires_password_grant_type(
    api_context,
):
    client, auth_service, _token_service = (
        api_context
    )

    identifier = _unique_identifier()

    user, _identity = (
        auth_service.register_password_user(
            identifier=identifier,
            password="CorrectPassword123!",
        )
    )

    try:
        response = client.post(
            "/auth/login",
            data={
                "grant_type": "client_credentials",
                "username": identifier,
                "password": "CorrectPassword123!",
            },
        )

        assert response.status_code == 422
    finally:
        _cleanup_user(user.id)


def test_me_returns_authenticated_user(
    api_context,
):
    client, _auth_service, _token_service = (
        api_context
    )

    identifier = _unique_identifier()

    register_response = client.post(
        "/auth/register",
        json={
            "identifier": identifier,
            "password": "CorrectPassword123!",
            "display_name": "Current User",
        },
    )

    assert register_response.status_code == 202
    user_id = _user_id_for_email(identifier)
    _mark_email_verified(user_id)

    try:
        login_body = _login_registered_user(
            client,
            identifier,
        )
        response = client.get(
            "/auth/me",
            headers={
                "Authorization": (
                    f"Bearer {login_body['access_token']}"
                )
            },
        )

        assert response.status_code == 200

        model = UserResponse.model_validate(
            response.json()
        )

        assert model.id == user_id
        assert model.display_name == (
            "Current User"
        )
    finally:
        _cleanup_user(user_id)


def test_me_without_token_returns_401(
    api_context,
):
    client, _auth_service, _token_service = (
        api_context
    )

    response = client.get(
        "/auth/me"
    )

    assert response.status_code == 401


def test_me_with_invalid_token_returns_401(
    api_context,
):
    client, _auth_service, _token_service = (
        api_context
    )

    response = client.get(
        "/auth/me",
        headers={
            "Authorization": "Bearer invalid-token"
        },
    )

    assert response.status_code == 401


def test_refresh_rotates_refresh_token(
    api_context,
):
    client, _auth_service, _token_service = (
        api_context
    )

    identifier = _unique_identifier()

    register_response = client.post(
        "/auth/register",
        json={
            "identifier": identifier,
            "password": "CorrectPassword123!",
        },
    )

    assert register_response.status_code == 202
    user_id = _user_id_for_email(identifier)
    _mark_email_verified(user_id)
    login_body = _login_registered_user(
        client,
        identifier,
    )
    old_refresh_token = login_body["refresh_token"]

    try:
        rotation_id = "e" * 64
        response = client.post(
            "/auth/refresh",
            json={
                "refresh_token": old_refresh_token,
                "rotation_id": rotation_id,
            },
        )

        assert response.status_code == 200

        rotated = response.json()

        assert (
            rotated["refresh_token"]
            != old_refresh_token
        )

        assert (
            rotated["access_token"]
            != login_body["access_token"]
        )

        # A lost response is recovered only when the same client idempotency
        # key is presented. The exact same replacement token is returned.
        recovered = client.post(
            "/auth/refresh",
            json={
                "refresh_token": old_refresh_token,
                "rotation_id": rotation_id,
            },
        )

        assert recovered.status_code == 200
        recovered_body = recovered.json()
        assert recovered_body["refresh_token"] == rotated["refresh_token"]

        active_session = client.get(
            "/auth/me",
            headers={
                "Authorization": (
                    f"Bearer {recovered_body['access_token']}"
                )
            },
        )

        assert active_session.status_code == 200
    finally:
        _cleanup_user(user_id)


def test_refresh_invalid_token_returns_401(
    api_context,
):
    client, _auth_service, _token_service = (
        api_context
    )

    response = client.post(
        "/auth/refresh",
        json={
            "refresh_token": "invalid-refresh-token"
        },
    )

    assert response.status_code == 401


def test_logout_revokes_current_session(
    api_context,
):
    client, _auth_service, _token_service = (
        api_context
    )

    identifier = _unique_identifier()

    register_response = client.post(
        "/auth/register",
        json={
            "identifier": identifier,
            "password": "CorrectPassword123!",
        },
    )

    assert register_response.status_code == 202
    user_id = _user_id_for_email(identifier)
    _mark_email_verified(user_id)
    login_body = _login_registered_user(
        client,
        identifier,
    )
    access_token = login_body["access_token"]

    try:
        logout_response = client.post(
            "/auth/logout",
            headers={
                "Authorization": (
                    f"Bearer {access_token}"
                )
            },
        )

        assert logout_response.status_code == 204

        me_response = client.get(
            "/auth/me",
            headers={
                "Authorization": (
                    f"Bearer {access_token}"
                )
            },
        )

        assert me_response.status_code == 401
    finally:
        _cleanup_user(user_id)


def test_logout_without_authentication_returns_401(
    api_context,
):
    client, _auth_service, _token_service = (
        api_context
    )

    response = client.post(
        "/auth/logout"
    )

    assert response.status_code == 401


def test_refresh_after_logout_returns_401(
    api_context,
):
    client, _auth_service, _token_service = (
        api_context
    )

    identifier = _unique_identifier()

    register_response = client.post(
        "/auth/register",
        json={
            "identifier": identifier,
            "password": "CorrectPassword123!",
        },
    )

    assert register_response.status_code == 202
    user_id = _user_id_for_email(identifier)
    _mark_email_verified(user_id)
    login_body = _login_registered_user(
        client,
        identifier,
    )

    try:
        logout_response = client.post(
            "/auth/logout",
            headers={
                "Authorization": (
                    f"Bearer {login_body['access_token']}"
                )
            },
        )

        assert logout_response.status_code == 204

        refresh_response = client.post(
            "/auth/refresh",
            json={
                "refresh_token": login_body[
                    "refresh_token"
                ]
            },
        )

        assert refresh_response.status_code == 401
    finally:
        _cleanup_user(user_id)


def test_access_token_from_one_user_cannot_be_changed_to_another(
    api_context,
):
    client, _auth_service, _token_service = (
        api_context
    )

    first_identifier = _unique_identifier()
    second_identifier = _unique_identifier()

    first = client.post(
        "/auth/register",
        json={
            "identifier": first_identifier,
            "password": "CorrectPassword123!",
        },
    )

    second = client.post(
        "/auth/register",
        json={
            "identifier": second_identifier,
            "password": "CorrectPassword123!",
        },
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["user"] is None
    assert second.json()["user"] is None

    first_user_id = _user_id_for_email(first_identifier)
    second_user_id = _user_id_for_email(second_identifier)
    _mark_email_verified(first_user_id)
    _mark_email_verified(second_user_id)

    try:
        first_login = _login_registered_user(
            client,
            first_identifier,
        )
        second_login = _login_registered_user(
            client,
            second_identifier,
        )

        response = client.get(
            "/auth/me",
            headers={
                "Authorization": (
                    f"Bearer {first_login['access_token']}"
                )
            },
        )

        assert response.status_code == 200
        assert (
            response.json()["id"]
            == first_user_id
        )

        second_claims = _token_service.decode_access_token(
            second_login["access_token"]
        )

        assert (
            second_claims["sub"]
            != first_user_id
        )
    finally:
        _cleanup_user(first_user_id)
        _cleanup_user(second_user_id)
