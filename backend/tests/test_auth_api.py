from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from api.auth import (
    get_auth_service,
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
from services.token_service import TokenService
from services.user_service import UserService


TEST_SECRET = (
    "api-test-secret-key-that-is-longer-than-32-characters"
)


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

    client = TestClient(app)

    try:
        yield client, auth_service, token_service
    finally:
        app.dependency_overrides.clear()


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


def test_register_returns_tokens_and_user(
    api_context,
):
    client, _auth_service, token_service = (
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

    assert response.status_code == 201

    body = response.json()

    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 600
    assert body["session_id"]
    assert body["user"]["display_name"] == (
        "API Test User"
    )

    claims = token_service.decode_access_token(
        body["access_token"]
    )

    assert claims["sub"] == body["user"]["id"]
    assert claims["sid"] == body["session_id"]

    _cleanup_user(
        body["user"]["id"]
    )


def test_register_duplicate_identifier_returns_400(
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

    assert first.status_code == 201

    user_id = first.json()["user"]["id"]

    try:
        second = client.post(
            "/auth/register",
            json={
                "identifier": identifier,
                "password": "AnotherPassword123!",
            },
        )

        assert second.status_code == 400
    finally:
        _cleanup_user(user_id)


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

    assert register_response.status_code == 201

    body = register_response.json()
    user_id = body["user"]["id"]

    try:
        response = client.get(
            "/auth/me",
            headers={
                "Authorization": (
                    f"Bearer {body['access_token']}"
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

    assert register_response.status_code == 201

    body = register_response.json()
    user_id = body["user"]["id"]
    old_refresh_token = body["refresh_token"]

    try:
        response = client.post(
            "/auth/refresh",
            json={
                "refresh_token": old_refresh_token
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
            != body["access_token"]
        )

        reused = client.post(
            "/auth/refresh",
            json={
                "refresh_token": old_refresh_token
            },
        )

        assert reused.status_code == 401
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

    assert register_response.status_code == 201

    body = register_response.json()
    user_id = body["user"]["id"]
    access_token = body["access_token"]

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

    assert register_response.status_code == 201

    body = register_response.json()
    user_id = body["user"]["id"]

    try:
        logout_response = client.post(
            "/auth/logout",
            headers={
                "Authorization": (
                    f"Bearer {body['access_token']}"
                )
            },
        )

        assert logout_response.status_code == 204

        refresh_response = client.post(
            "/auth/refresh",
            json={
                "refresh_token": body[
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

    assert first.status_code == 201
    assert second.status_code == 201

    first_body = first.json()
    second_body = second.json()

    try:
        response = client.get(
            "/auth/me",
            headers={
                "Authorization": (
                    f"Bearer {first_body['access_token']}"
                )
            },
        )

        assert response.status_code == 200
        assert (
            response.json()["id"]
            == first_body["user"]["id"]
        )

        second_claims = _token_service.decode_access_token(
            second_body["access_token"]
        )

        assert (
            second_claims["sub"]
            != first_body["user"]["id"]
        )
    finally:
        _cleanup_user(
            first_body["user"]["id"]
        )
        _cleanup_user(
            second_body["user"]["id"]
        )
