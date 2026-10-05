from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from database.connection import engine
from models.auth_identity import AuthIdentity
from models.password_reset_challenge import PasswordResetChallenge
from models.user import User
from models.user_session import UserSession
from services.auth_service import AuthService
from services.password_reset_service import (
    PasswordResetError,
    PasswordResetRateLimited,
    PasswordResetService,
)


TEST_SECRET = "password-reset-test-secret-key-that-is-longer-than-32-characters"


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
            delete(User).where(
                User.id == user_id
            )
        )
        session.commit()


def _extract_code(message_body: str) -> str:
    match = re.search(r"code is (\d{6})", message_body)
    assert match is not None
    return match.group(1)


@pytest.fixture
def reset_service():
    notifications = FakeEmailNotificationService()
    service = PasswordResetService(
        notification_service=notifications,
        engine=engine,
        secret_key=TEST_SECRET,
    )
    service._test_notifications = notifications
    return service


def test_request_reset_stores_hashed_code_and_sends_email(
    reset_service,
    monkeypatch,
):
    monkeypatch.setattr(
        PasswordResetService,
        "_generate_code",
        classmethod(lambda cls: "123456"),
    )

    identifier = f"reset-{uuid4().hex[:12]}@example.test"
    user, _identity = AuthService(engine=engine).register_password_user(
        identifier=identifier,
        password="OldPassword123!",
    )

    try:
        assert reset_service.request_reset(email=identifier) is True

        notifications = reset_service._test_notifications
        assert len(notifications.messages) == 1
        assert notifications.messages[0]["to"] == identifier
        assert _extract_code(notifications.messages[0]["body"]) == "123456"

        with Session(engine) as session:
            challenge = session.scalar(
                select(PasswordResetChallenge).where(
                    PasswordResetChallenge.user_id == user.id
                )
            )

        assert challenge is not None
        assert challenge.code_hash != "123456"
        assert challenge.attempt_count == 0
        assert challenge.used_at is None
    finally:
        _cleanup_user(user.id)


def test_wrong_code_is_bounded_to_five_attempts(
    reset_service,
    monkeypatch,
):
    monkeypatch.setattr(
        PasswordResetService,
        "_generate_code",
        classmethod(lambda cls: "123456"),
    )

    identifier = f"reset-{uuid4().hex[:12]}@example.test"
    user, _identity = AuthService(engine=engine).register_password_user(
        identifier=identifier,
        password="OldPassword123!",
    )

    try:
        reset_service.request_reset(email=identifier)

        for _attempt in range(4):
            with pytest.raises(PasswordResetError):
                reset_service.reset_password(
                    email=identifier,
                    code="000000",
                    new_password="NewPassword123!",
                )

        with pytest.raises(
            PasswordResetError,
            match="Too many incorrect attempts",
        ):
            reset_service.reset_password(
                email=identifier,
                code="000000",
                new_password="NewPassword123!",
            )

        with Session(engine) as session:
            challenge = session.scalar(
                select(PasswordResetChallenge).where(
                    PasswordResetChallenge.user_id == user.id
                )
            )

        assert challenge is not None
        assert challenge.attempt_count == 5
    finally:
        _cleanup_user(user.id)


def test_reset_changes_password_and_revokes_existing_sessions(
    reset_service,
    monkeypatch,
):
    monkeypatch.setattr(
        PasswordResetService,
        "_generate_code",
        classmethod(lambda cls: "654321"),
    )

    identifier = f"reset-{uuid4().hex[:12]}@example.test"
    auth_service = AuthService(engine=engine)
    user, _identity = auth_service.register_password_user(
        identifier=identifier,
        password="OldPassword123!",
    )
    old_session, _refresh_token = auth_service.create_session(user.id)
    old_session_id = old_session.id

    try:
        reset_service.request_reset(email=identifier)

        reset_user = reset_service.reset_password(
            email=identifier,
            code="654321",
            new_password="NewPassword123!",
        )

        assert reset_user.id == user.id
        assert (
            auth_service.authenticate_password(
                identifier,
                "OldPassword123!",
            )
            is None
        )
        assert (
            auth_service.authenticate_password(
                identifier,
                "NewPassword123!",
            )
            is not None
        )

        with Session(engine) as session:
            stored_session = session.get(
                UserSession,
                old_session_id,
            )
            assert stored_session is not None
            assert stored_session.revoked_at is not None

            challenge = session.scalar(
                select(PasswordResetChallenge).where(
                    PasswordResetChallenge.user_id == user.id
                )
            )

        assert challenge is not None
        assert challenge.used_at is not None

        with pytest.raises(PasswordResetError):
            reset_service.reset_password(
                email=identifier,
                code="654321",
                new_password="AnotherPassword123!",
            )
    finally:
        _cleanup_user(user.id)


def test_expired_reset_code_is_rejected(
    reset_service,
    monkeypatch,
):
    monkeypatch.setattr(
        PasswordResetService,
        "_generate_code",
        classmethod(lambda cls: "111111"),
    )

    identifier = f"reset-{uuid4().hex[:12]}@example.test"
    user, _identity = AuthService(engine=engine).register_password_user(
        identifier=identifier,
        password="OldPassword123!",
    )

    try:
        reset_service.request_reset(email=identifier)

        with Session(engine) as session:
            challenge = session.scalar(
                select(PasswordResetChallenge).where(
                    PasswordResetChallenge.user_id == user.id
                )
            )
            assert challenge is not None
            challenge.expires_at = (
                datetime.now(timezone.utc).replace(tzinfo=None)
                - timedelta(seconds=1)
            )
            session.commit()

        with pytest.raises(
            PasswordResetError,
            match="expired",
        ):
            reset_service.reset_password(
                email=identifier,
                code="111111",
                new_password="NewPassword123!",
            )
    finally:
        _cleanup_user(user.id)


def test_reset_code_resend_cooldown_is_enforced(
    reset_service,
    monkeypatch,
):
    monkeypatch.setattr(
        PasswordResetService,
        "_generate_code",
        classmethod(lambda cls: "222222"),
    )

    identifier = f"reset-{uuid4().hex[:12]}@example.test"
    user, _identity = AuthService(engine=engine).register_password_user(
        identifier=identifier,
        password="OldPassword123!",
    )

    try:
        assert reset_service.request_reset(email=identifier) is True

        with pytest.raises(
            PasswordResetRateLimited,
            match="Please wait",
        ):
            reset_service.request_reset(email=identifier)
    finally:
        _cleanup_user(user.id)
