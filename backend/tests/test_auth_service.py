from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from database.connection import engine
from models.auth_identity import AuthIdentity
from models.user import User
from models.user_session import UserSession
from services.auth_service import AuthService


def _cleanup_user(user_id: str) -> None:
    with Session(engine) as session:
        session.execute(
            delete(UserSession)
            .where(UserSession.user_id == user_id)
        )

        session.execute(
            delete(AuthIdentity)
            .where(AuthIdentity.user_id == user_id)
        )

        session.execute(
            delete(User)
            .where(User.id == user_id)
        )

        session.commit()


@pytest.fixture
def auth_service():
    return AuthService(engine=engine)


@pytest.fixture
def test_identifier():
    return f"auth-test-{uuid4().hex[:12]}@example.test"


@pytest.fixture
def test_user(auth_service, test_identifier):
    user, identity = auth_service.register_password_user(
        identifier=test_identifier,
        password="CorrectPassword123!",
        display_name="Auth Test User",
    )

    try:
        yield user, identity
    finally:
        _cleanup_user(user.id)


def test_register_password_user_creates_user_and_identity(
    auth_service,
    test_identifier,
):
    user, identity = auth_service.register_password_user(
        identifier=test_identifier,
        password="CorrectPassword123!",
        display_name="Auth Test User",
    )

    try:
        assert user.id
        assert user.is_active is True
        assert user.display_name == "Auth Test User"

        assert identity.user_id == user.id
        assert identity.provider == "password"
        assert identity.provider_subject == test_identifier
        assert identity.password_hash
        assert identity.password_hash != "CorrectPassword123!"

        assert auth_service._verify_password(
            "CorrectPassword123!",
            identity.password_hash,
        )
    finally:
        _cleanup_user(user.id)


def test_register_password_user_normalizes_identifier(
    auth_service,
):
    identifier = f"  MixedCase-{uuid4().hex[:8]}@Example.TEST  "

    user, identity = auth_service.register_password_user(
        identifier=identifier,
        password="CorrectPassword123!",
    )

    try:
        assert identity.provider_subject == identifier.strip().lower()
    finally:
        _cleanup_user(user.id)


def test_register_password_user_rejects_short_password(
    auth_service,
    test_identifier,
):
    with pytest.raises(ValueError):
        auth_service.register_password_user(
            identifier=test_identifier,
            password="short",
        )


def test_register_password_user_rejects_empty_identifier(
    auth_service,
):
    with pytest.raises(ValueError):
        auth_service.register_password_user(
            identifier=" ",
            password="CorrectPassword123!",
        )


def test_duplicate_password_identifier_is_rejected(
    auth_service,
    test_identifier,
):
    user, _ = auth_service.register_password_user(
        identifier=test_identifier,
        password="CorrectPassword123!",
    )

    try:
        with pytest.raises(ValueError):
            auth_service.register_password_user(
                identifier=test_identifier,
                password="AnotherPassword123!",
            )
    finally:
        _cleanup_user(user.id)


def test_authenticate_password_success(
    auth_service,
    test_user,
    test_identifier,
):
    user, _ = test_user

    authenticated = auth_service.authenticate_password(
        identifier=test_identifier,
        password="CorrectPassword123!",
    )

    assert authenticated is not None
    assert authenticated.id == user.id


def test_authenticate_password_wrong_password_returns_none(
    auth_service,
    test_user,
    test_identifier,
):
    authenticated = auth_service.authenticate_password(
        identifier=test_identifier,
        password="WrongPassword123!",
    )

    assert authenticated is None


def test_authenticate_password_unknown_identifier_returns_none(
    auth_service,
):
    authenticated = auth_service.authenticate_password(
        identifier=f"unknown-{uuid4().hex[:12]}@example.test",
        password="CorrectPassword123!",
    )

    assert authenticated is None


def test_authenticate_password_inactive_user_returns_none(
    auth_service,
    test_user,
    test_identifier,
):
    user, _ = test_user

    with Session(engine) as session:
        persisted_user = session.get(User, user.id)
        assert persisted_user is not None

        persisted_user.is_active = False
        session.commit()

    authenticated = auth_service.authenticate_password(
        identifier=test_identifier,
        password="CorrectPassword123!",
    )

    assert authenticated is None


def test_create_session_returns_raw_token_but_stores_only_hash(
    auth_service,
    test_user,
):
    user, _ = test_user

    user_session, refresh_token = auth_service.create_session(
        user.id,
    )

    try:
        assert user_session.id
        assert refresh_token
        assert len(refresh_token) > 40
        assert user_session.refresh_token_hash
        assert user_session.refresh_token_hash != refresh_token
        assert len(user_session.refresh_token_hash) == 64
        assert user_session.user_id == user.id
        assert user_session.revoked_at is None
        assert user_session.expires_at > user_session.created_at
    finally:
        with Session(engine) as session:
            session.delete(user_session)
            session.commit()


def test_create_session_rejects_unknown_user(
    auth_service,
):
    with pytest.raises(ValueError):
        auth_service.create_session(
            str(uuid4()),
        )


def test_get_session_by_refresh_token(
    auth_service,
    test_user,
):
    user, _ = test_user

    user_session, refresh_token = auth_service.create_session(
        user.id,
    )

    try:
        found = auth_service.get_session_by_refresh_token(
            refresh_token,
        )

        assert found is not None
        assert found.id == user_session.id
    finally:
        with Session(engine) as session:
            session.delete(user_session)
            session.commit()


def test_rotate_session_replaces_refresh_token(
    auth_service,
    test_user,
):
    user, _ = test_user

    user_session, old_refresh_token = (
        auth_service.create_session(
            user.id,
        )
    )

    try:
        rotated_session, new_refresh_token = (
            auth_service.rotate_session(
                old_refresh_token,
            )
        )

        assert rotated_session.id == user_session.id
        assert new_refresh_token
        assert new_refresh_token != old_refresh_token

        assert (
            auth_service.get_session_by_refresh_token(
                old_refresh_token,
            )
            is None
        )

        found = auth_service.get_session_by_refresh_token(
            new_refresh_token,
        )

        assert found is not None
        assert found.id == user_session.id
    finally:
        with Session(engine) as session:
            session.delete(
                session.get(
                    UserSession,
                    user_session.id,
                )
            )
            session.commit()


def test_reusing_rotated_refresh_token_is_rejected(
    auth_service,
    test_user,
):
    user, _ = test_user

    user_session, old_refresh_token = (
        auth_service.create_session(
            user.id,
        )
    )

    try:
        auth_service.rotate_session(
            old_refresh_token,
        )

        with pytest.raises(ValueError):
            auth_service.rotate_session(
                old_refresh_token,
            )
    finally:
        with Session(engine) as session:
            session.delete(
                session.get(
                    UserSession,
                    user_session.id,
                )
            )
            session.commit()


def test_revoked_session_cannot_be_rotated(
    auth_service,
    test_user,
):
    user, _ = test_user

    user_session, refresh_token = (
        auth_service.create_session(
            user.id,
        )
    )

    try:
        assert auth_service.revoke_session(
            user_session.id,
        )

        with pytest.raises(ValueError):
            auth_service.rotate_session(
                refresh_token,
            )
    finally:
        with Session(engine) as session:
            session.delete(
                session.get(
                    UserSession,
                    user_session.id,
                )
            )
            session.commit()


def test_revoke_session_is_idempotent(
    auth_service,
    test_user,
):
    user, _ = test_user

    user_session, _ = auth_service.create_session(
        user.id,
    )

    try:
        assert auth_service.revoke_session(
            user_session.id,
        )

        assert (
            auth_service.revoke_session(
                user_session.id,
            )
            is False
        )
    finally:
        with Session(engine) as session:
            session.delete(
                session.get(
                    UserSession,
                    user_session.id,
                )
            )
            session.commit()


def test_session_expiration_is_rejected(
    auth_service,
    test_user,
):
    user, _ = test_user

    user_session, refresh_token = (
        auth_service.create_session(
            user.id,
        )
    )

    try:
        with Session(engine) as session:
            persisted = session.get(
                UserSession,
                user_session.id,
            )
            assert persisted is not None

            persisted.expires_at = (
                persisted.created_at
                - timedelta(seconds=1)
            )
            session.commit()

        with pytest.raises(ValueError):
            auth_service.rotate_session(
                refresh_token,
            )
    finally:
        with Session(engine) as session:
            session.delete(
                session.get(
                    UserSession,
                    user_session.id,
                )
            )
            session.commit()
