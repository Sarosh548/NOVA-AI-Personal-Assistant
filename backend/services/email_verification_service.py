from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from email.utils import parseaddr

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from database.connection import engine as default_engine
from models.auth_identity import AuthIdentity
from models.email_verification_challenge import (
    EmailVerificationChallenge,
)
from models.user import User
from services.notification_service import NotificationService


class EmailNotVerified(ValueError):
    """Raised when an email-backed account has not been verified."""


class EmailVerificationError(ValueError):
    """Raised for user-correctable email verification failures."""


class EmailVerificationRateLimited(EmailVerificationError):
    """Raised when a verification code was sent too recently."""


class EmailVerificationService:
    CODE_LENGTH = 6
    CODE_SPACE = 1_000_000
    EXPIRY_MINUTES = 10
    MAX_ATTEMPTS = 5
    RESEND_COOLDOWN_SECONDS = 60

    def __init__(
        self,
        *,
        notification_service: NotificationService,
        engine=None,
        secret_key: str | None = None,
    ):
        self.notification_service = notification_service
        self.engine = engine or default_engine
        self.secret_key = (
            str(secret_key)
            if secret_key
            else None
        )

    @staticmethod
    def is_email_identifier(identifier: str) -> bool:
        normalized = str(identifier).strip()
        _, address = parseaddr(normalized)
        local_part, separator, domain = normalized.rpartition("@")
        return bool(
            normalized
            and address == normalized
            and separator
            and local_part
            and domain
            and "." in domain
        )

    @classmethod
    def normalize_email(cls, identifier: str) -> str:
        normalized = str(identifier).strip().lower()

        if not cls.is_email_identifier(normalized):
            raise EmailVerificationError(
                "A valid email address is required for new NOVA accounts."
            )

        if len(normalized) > 255:
            raise EmailVerificationError(
                "Email address cannot exceed 255 characters."
            )

        return normalized

    @classmethod
    def _generate_code(cls) -> str:
        return f"{secrets.randbelow(cls.CODE_SPACE):0{cls.CODE_LENGTH}d}"

    def _hash_code(self, *, code: str, salt: str) -> str:
        if not self.secret_key:
            raise RuntimeError(
                "Email verification secret is not configured."
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

        if user is None:
            return None

        return user, identity

    def _invalidate_unused_challenges(
        self,
        *,
        session: Session,
        user_id: str,
        now: datetime,
    ) -> None:
        session.execute(
            update(EmailVerificationChallenge)
            .where(
                EmailVerificationChallenge.user_id == user_id,
                EmailVerificationChallenge.used_at.is_(None),
            )
            .values(
                used_at=now,
                updated_at=now,
            )
        )

    def _check_resend_cooldown(
        self,
        *,
        session: Session,
        user_id: str,
        now: datetime,
    ) -> None:
        latest = session.scalar(
            select(EmailVerificationChallenge)
            .where(
                EmailVerificationChallenge.user_id == user_id,
            )
            .order_by(
                EmailVerificationChallenge.created_at.desc()
            )
            .limit(1)
        )

        if latest is None:
            return

        elapsed = (
            now - latest.sent_at
        ).total_seconds()

        if elapsed < self.RESEND_COOLDOWN_SECONDS:
            remaining = max(
                1,
                int(
                    self.RESEND_COOLDOWN_SECONDS
                    - elapsed
                ),
            )
            raise EmailVerificationRateLimited(
                "Please wait "
                f"{remaining} seconds before requesting another code."
            )

    def issue_verification_code(
        self,
        *,
        email: str,
        user_id: str,
        enforce_cooldown: bool = False,
    ) -> bool:
        normalized_email = self.normalize_email(email)
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        if not self.secret_key:
            raise RuntimeError(
                "Email verification secret is not configured."
            )

        with Session(self.engine) as session:
            user_identity = self._find_email_identity(
                session=session,
                email=normalized_email,
            )

            if user_identity is None:
                raise EmailVerificationError(
                    "No account exists for that email address."
                )

            user, _identity = user_identity

            if user.id != user_id:
                raise EmailVerificationError(
                    "Email verification account mismatch."
                )

            if user.email_verified_at is not None:
                return True

            if enforce_cooldown:
                self._check_resend_cooldown(
                    session=session,
                    user_id=user.id,
                    now=now,
                )

            self._invalidate_unused_challenges(
                session=session,
                user_id=user.id,
                now=now,
            )

            code = self._generate_code()
            salt = secrets.token_hex(16)

            challenge = EmailVerificationChallenge(
                user_id=user.id,
                code_hash=self._hash_code(
                    code=code,
                    salt=salt,
                ),
                code_salt=salt,
                expires_at=(
                    now
                    + timedelta(
                        minutes=self.EXPIRY_MINUTES
                    )
                ),
                attempt_count=0,
                used_at=None,
                sent_at=now,
                created_at=now,
                updated_at=now,
            )

            session.add(challenge)
            session.commit()

        sent = self.notification_service.send_email(
            user_id=user_id,
            to=normalized_email,
            subject="Verify your NOVA email",
            body=(
                "Your NOVA verification code is "
                f"{code}.\n\n"
                "This code expires in "
                f"{self.EXPIRY_MINUTES} minutes and can be used once."
            ),
        )

        return bool(sent)

    def verify_code(
        self,
        *,
        email: str,
        code: str,
    ) -> User:
        normalized_email = self.normalize_email(email)
        normalized_code = str(code).strip()

        if (
            len(normalized_code) != self.CODE_LENGTH
            or not normalized_code.isdigit()
        ):
            raise EmailVerificationError(
                "Verification code must be 6 digits."
            )

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        with Session(self.engine) as session:
            user_identity = self._find_email_identity(
                session=session,
                email=normalized_email,
            )

            if user_identity is None:
                raise EmailVerificationError(
                    "No account exists for that email address."
                )

            user, _identity = user_identity

            if user.email_verified_at is not None:
                return user

            challenge = session.scalar(
                select(EmailVerificationChallenge)
                .where(
                    EmailVerificationChallenge.user_id == user.id,
                    EmailVerificationChallenge.used_at.is_(None),
                )
                .order_by(
                    EmailVerificationChallenge.created_at.desc()
                )
                .limit(1)
                .with_for_update()
            )

            if challenge is None:
                raise EmailVerificationError(
                    "No active verification code was found. Request a new code."
                )

            if challenge.expires_at <= now:
                raise EmailVerificationError(
                    "This verification code has expired. Request a new code."
                )

            if challenge.attempt_count >= self.MAX_ATTEMPTS:
                raise EmailVerificationError(
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
                    raise EmailVerificationError(
                        "Too many incorrect attempts. Request a new code."
                    )

                raise EmailVerificationError(
                    "Invalid verification code. "
                    f"{remaining} attempts remaining."
                )

            challenge.used_at = now
            challenge.updated_at = now
            user.email_verified_at = now
            user.updated_at = now

            session.execute(
                update(EmailVerificationChallenge)
                .where(
                    EmailVerificationChallenge.user_id == user.id,
                    EmailVerificationChallenge.id != challenge.id,
                    EmailVerificationChallenge.used_at.is_(None),
                )
                .values(
                    used_at=now,
                    updated_at=now,
                )
            )

            session.commit()
            session.refresh(user)

            return user
