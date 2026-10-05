from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from database.connection import engine
from models.auth_identity import AuthIdentity
from models.email_verification_challenge import (
    EmailVerificationChallenge,
)
from models.user import User
from models.user_session import UserSession
from services.auth_service import AuthService
from services.email_verification_service import (
    EmailVerificationError,
    EmailVerificationRateLimited,
    EmailVerificationService,
)


class FakeEmailNotificationService:
    def __init__(self):
        self.messages: list[dict[str, str]] = []

    def send_email(
        self,
        *,
        user_id: str,
        to: str,
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
            delete(EmailVerificationChallenge).where(
                EmailVerificationChallenge.user_id == user_id
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


def _create_user(email: str) -> str:
    user, _identity = AuthService(
        engine=engine
    ).register_password_user(
        identifier=email,
        password="CorrectPassword123!",
        display_name="Verification Test",
    )
    return user.id


def _extract_code(body: str) -> str:
    marker = "Your NOVA verification code is "
    start = body.index(marker) + len(marker)
    return body[start : start + 6]


def test_issue_verification_code_stores_only_hash_and_sends_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        EmailVerificationService,
        "_generate_code",
        classmethod(lambda cls: "123456"),
    )

    email = f"verify-{uuid4().hex[:12]}@example.test"
    user_id = _create_user(email)
    notification = FakeEmailNotificationService()
    service = EmailVerificationService(
        notification_service=notification,
        engine=engine,
        secret_key="verification-test-secret",
    )

    try:
        assert service.issue_verification_code(
            email=email,
            user_id=user_id,
        ) is True

        assert len(notification.messages) == 1
        message = notification.messages[0]
        assert message["to"] == email
        assert message["subject"] == "Verify your NOVA email"
        assert _extract_code(message["body"]) == "123456"

        with Session(engine) as session:
            challenge = session.scalar(
                select(EmailVerificationChallenge).where(
                    EmailVerificationChallenge.user_id == user_id
                )
            )
            assert challenge is not None
            assert challenge.code_hash != "123456"
            assert challenge.code_salt
            assert challenge.expires_at > challenge.created_at
            assert challenge.attempt_count == 0
            assert challenge.used_at is None

    finally:
        _cleanup_user(user_id)


def test_verify_email_marks_user_verified_and_code_cannot_be_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        EmailVerificationService,
        "_generate_code",
        classmethod(lambda cls: "654321"),
    )

    email = f"verify-{uuid4().hex[:12]}@example.test"
    user_id = _create_user(email)
    notification = FakeEmailNotificationService()
    service = EmailVerificationService(
        notification_service=notification,
        engine=engine,
        secret_key="verification-test-secret",
    )

    try:
        service.issue_verification_code(
            email=email,
            user_id=user_id,
        )

        verified = service.verify_code(
            email=email,
            code="654321",
        )
        assert verified.id == user_id
        assert verified.email_verified_at is not None

        with Session(engine) as session:
            challenge = session.scalar(
                select(EmailVerificationChallenge).where(
                    EmailVerificationChallenge.user_id == user_id
                )
            )
            assert challenge is not None
            assert challenge.used_at is not None

        verified_again = service.verify_code(
            email=email,
            code="654321",
        )
        assert verified_again.id == user_id

    finally:
        _cleanup_user(user_id)


def test_wrong_code_is_bounded_to_five_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        EmailVerificationService,
        "_generate_code",
        classmethod(lambda cls: "111222"),
    )

    email = f"verify-{uuid4().hex[:12]}@example.test"
    user_id = _create_user(email)
    service = EmailVerificationService(
        notification_service=FakeEmailNotificationService(),
        engine=engine,
        secret_key="verification-test-secret",
    )

    try:
        service.issue_verification_code(
            email=email,
            user_id=user_id,
        )

        for attempt in range(1, 5):
            with pytest.raises(
                EmailVerificationError,
                match=f"{5 - attempt} attempts remaining",
            ):
                service.verify_code(
                    email=email,
                    code="999999",
                )

        with pytest.raises(
            EmailVerificationError,
            match="Too many incorrect attempts",
        ):
            service.verify_code(
                email=email,
                code="999999",
            )

    finally:
        _cleanup_user(user_id)


def test_expired_code_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        EmailVerificationService,
        "_generate_code",
        classmethod(lambda cls: "333444"),
    )

    email = f"verify-{uuid4().hex[:12]}@example.test"
    user_id = _create_user(email)
    service = EmailVerificationService(
        notification_service=FakeEmailNotificationService(),
        engine=engine,
        secret_key="verification-test-secret",
    )

    try:
        service.issue_verification_code(
            email=email,
            user_id=user_id,
        )

        with Session(engine) as session:
            challenge = session.scalar(
                select(EmailVerificationChallenge).where(
                    EmailVerificationChallenge.user_id == user_id
                )
            )
            assert challenge is not None
            challenge.expires_at = (
                datetime.now(timezone.utc).replace(tzinfo=None)
                - timedelta(seconds=1)
            )
            session.commit()

        with pytest.raises(
            EmailVerificationError,
            match="expired",
        ):
            service.verify_code(
                email=email,
                code="333444",
            )

    finally:
        _cleanup_user(user_id)


def test_resend_verification_obeys_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codes = iter(["444555", "666777"])
    monkeypatch.setattr(
        EmailVerificationService,
        "_generate_code",
        classmethod(lambda cls: next(codes)),
    )

    email = f"verify-{uuid4().hex[:12]}@example.test"
    user_id = _create_user(email)
    service = EmailVerificationService(
        notification_service=FakeEmailNotificationService(),
        engine=engine,
        secret_key="verification-test-secret",
    )

    try:
        service.issue_verification_code(
            email=email,
            user_id=user_id,
        )

        with pytest.raises(
            EmailVerificationRateLimited,
            match="wait",
        ):
            service.issue_verification_code(
                email=email,
                user_id=user_id,
                enforce_cooldown=True,
            )

    finally:
        _cleanup_user(user_id)
