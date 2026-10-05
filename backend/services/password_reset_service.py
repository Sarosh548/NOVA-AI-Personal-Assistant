from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

from pwdlib import PasswordHash
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from database.connection import engine as default_engine
from models.auth_identity import AuthIdentity
from models.password_reset_challenge import PasswordResetChallenge
from models.user import User
from models.user_session import UserSession
from services.email_verification_service import EmailVerificationService
from services.notification_service import NotificationService


class PasswordResetError(ValueError):
    """Raised for user-correctable password reset failures."""


class PasswordResetRateLimited(PasswordResetError):
    """Raised when a password reset code was sent too recently."""


class PasswordResetService:
    CODE_LENGTH = 6
    CODE_SPACE = 1_000_000
    EXPIRY_MINUTES = 10
    MAX_ATTEMPTS = 5
    RESEND_COOLDOWN_SECONDS = 60

    MIN_PASSWORD_LENGTH = 8
    MAX_PASSWORD_LENGTH = 256

    _password_hash = PasswordHash.recommended()

    def __init__(
        self,
        *,
        notification_service: NotificationService,
        engine=None,
        secret_key: str | None = None,
    ):
        self.notification_service = notification_service
        self.engine = engine or default_engine
        self.secret_key = str(secret_key) if secret_key else None

    @classmethod
    def _validate_password(cls, password: str) -> str:
        if not isinstance(password, str):
            raise PasswordResetError("password must be a string.")

        if len(password) < cls.MIN_PASSWORD_LENGTH:
            raise PasswordResetError(
                f"password must be at least {cls.MIN_PASSWORD_LENGTH} characters."
            )

        if len(password) > cls.MAX_PASSWORD_LENGTH:
            raise PasswordResetError(
                f"password cannot exceed {cls.MAX_PASSWORD_LENGTH} characters."
            )

        return password

    @classmethod
    def _generate_code(cls) -> str:
        return f"{secrets.randbelow(cls.CODE_SPACE):0{cls.CODE_LENGTH}d}"

    def _hash_code(self, *, code: str, salt: str) -> str:
        if not self.secret_key:
            raise RuntimeError(
                "Password reset secret is not configured."
            )

        payload = f"{salt}:{code}".encode("utf-8")
        return hmac.new(
            self.secret_key.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

    def _find_email_identity(
        self,
        *,
        session: Session,
        email: str,
    ) -> tuple[User, AuthIdentity] | None:
        identity = session.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == "password",
                AuthIdentity.provider_subject == email,
            )
        )

        if identity is None:
            return None

        user = session.get(User, identity.user_id)

        if user is None or not user.is_active:
            return None

        return user, identity

    def _check_resend_cooldown(
        self,
        *,
        session: Session,
        user_id: str,
        now: datetime,
    ) -> None:
        latest = session.scalar(
            select(PasswordResetChallenge)
            .where(
                PasswordResetChallenge.user_id == user_id,
            )
            .order_by(
                PasswordResetChallenge.created_at.desc()
            )
            .limit(1)
        )

        if latest is None:
            return

        elapsed = (now - latest.sent_at).total_seconds()

        if elapsed < self.RESEND_COOLDOWN_SECONDS:
            remaining = max(
                1,
                int(
                    self.RESEND_COOLDOWN_SECONDS
                    - elapsed
                ),
            )
            raise PasswordResetRateLimited(
                "Please wait "
                f"{remaining} seconds before requesting another code."
            )

    def _invalidate_unused_challenges(
        self,
        *,
        session: Session,
        user_id: str,
        now: datetime,
    ) -> None:
        session.execute(
            update(PasswordResetChallenge)
            .where(
                PasswordResetChallenge.user_id == user_id,
                PasswordResetChallenge.used_at.is_(None),
            )
            .values(
                used_at=now,
                updated_at=now,
            )
        )

    def request_reset(self, *, email: str) -> bool:
        normalized_email = EmailVerificationService.normalize_email(email)

        if not self.secret_key:
            raise RuntimeError(
                "Password reset secret is not configured."
            )

        code = self._generate_code()
        salt = secrets.token_hex(16)
        code_hash = self._hash_code(
            code=code,
            salt=salt,
        )
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        expires_at = now + timedelta(minutes=self.EXPIRY_MINUTES)

        with Session(self.engine) as session:
            user_identity = self._find_email_identity(
                session=session,
                email=normalized_email,
            )

            if user_identity is None:
                return False

            user, _identity = user_identity
            user_id = user.id

            self._check_resend_cooldown(
                session=session,
                user_id=user_id,
                now=now,
            )
            self._invalidate_unused_challenges(
                session=session,
                user_id=user_id,
                now=now,
            )

            challenge = PasswordResetChallenge(
                user_id=user_id,
                code_hash=code_hash,
                code_salt=salt,
                expires_at=expires_at,
                attempt_count=0,
                used_at=None,
                sent_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(challenge)
            session.flush()
            challenge_id = challenge.id
            session.commit()

        sent = self.notification_service.send_email(
            user_id=user_id,
            to=normalized_email,
            subject="Reset your NOVA password",
            body=(
                "Your NOVA password reset code is "
                f"{code}.\n\n"
                "This code expires in "
                f"{self.EXPIRY_MINUTES} minutes and can be used once."
            ),
        )

        if sent:
            return True

        with Session(self.engine) as session:
            failed_challenge = session.get(
                PasswordResetChallenge,
                challenge_id,
            )
            if failed_challenge is not None:
                session.delete(failed_challenge)
                session.commit()

        return False

    def reset_password(
        self,
        *,
        email: str,
        code: str,
        new_password: str,
    ) -> User:
        normalized_email = EmailVerificationService.normalize_email(email)
        normalized_code = str(code).strip()
        validated_password = self._validate_password(new_password)

        if (
            len(normalized_code) != self.CODE_LENGTH
            or not normalized_code.isdigit()
        ):
            raise PasswordResetError(
                "Reset code must be 6 digits."
            )

        if not self.secret_key:
            raise RuntimeError(
                "Password reset secret is not configured."
            )

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        with Session(self.engine) as session:
            user_identity = self._find_email_identity(
                session=session,
                email=normalized_email,
            )

            if user_identity is None:
                raise PasswordResetError(
                    "Invalid or expired password reset request."
                )

            user, identity = user_identity

            challenge = session.scalar(
                select(PasswordResetChallenge)
                .where(
                    PasswordResetChallenge.user_id == user.id,
                    PasswordResetChallenge.used_at.is_(None),
                )
                .order_by(
                    PasswordResetChallenge.created_at.desc()
                )
                .limit(1)
                .with_for_update()
            )

            if challenge is None:
                raise PasswordResetError(
                    "No active password reset code was found. Request a new code."
                )

            if challenge.expires_at <= now:
                raise PasswordResetError(
                    "This password reset code has expired. Request a new code."
                )

            if challenge.attempt_count >= self.MAX_ATTEMPTS:
                raise PasswordResetError(
                    "Too many incorrect attempts. Request a new code."
                )

            expected_hash = self._hash_code(
                code=normalized_code,
                salt=challenge.code_salt,
            )

            if not hmac.compare_digest(
                expected_hash,
                challenge.code_hash,
            ):
                challenge.attempt_count += 1
                challenge.updated_at = now
                session.commit()

                remaining = max(
                    0,
                    self.MAX_ATTEMPTS
                    - challenge.attempt_count,
                )

                if remaining == 0:
                    raise PasswordResetError(
                        "Too many incorrect attempts. Request a new code."
                    )

                raise PasswordResetError(
                    "Invalid password reset code. "
                    f"{remaining} attempts remaining."
                )

            identity.password_hash = self._password_hash.hash(
                validated_password
            )
            identity.updated_at = now
            user.email_verified_at = user.email_verified_at or now
            user.updated_at = now

            challenge.used_at = now
            challenge.updated_at = now

            session.execute(
                update(PasswordResetChallenge)
                .where(
                    PasswordResetChallenge.user_id == user.id,
                    PasswordResetChallenge.id != challenge.id,
                    PasswordResetChallenge.used_at.is_(None),
                )
                .values(
                    used_at=now,
                    updated_at=now,
                )
            )

            session.execute(
                update(UserSession)
                .where(
                    UserSession.user_id == user.id,
                    UserSession.revoked_at.is_(None),
                )
                .values(
                    revoked_at=now,
                    updated_at=now,
                )
            )

            session.commit()
            session.refresh(user)

            return user
