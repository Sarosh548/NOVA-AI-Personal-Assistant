from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Any

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.connection import engine as default_engine
from models.auth_identity import AuthIdentity
from models.user import User
from models.user_session import UserSession
from models.refresh_token_history import RefreshTokenHistory


class RefreshTokenReplayDetected(ValueError):
    """Raised when a previously rotated refresh token is replayed."""

    def __init__(
        self,
        *,
        user_id: str,
        session_id: str,
    ):
        self.user_id = user_id
        self.session_id = session_id
        super().__init__("Refresh token replay detected.")


class AuthService:
    """
    Core authentication and session lifecycle service.

    This service intentionally does not expose HTTP concerns or
    JWT handling. It owns local password identities and durable
    refresh-token-backed sessions.
    """

    PASSWORD_PROVIDER = "password"

    MIN_PASSWORD_LENGTH = 8
    MAX_PASSWORD_LENGTH = 256

    MAX_IDENTIFIER_LENGTH = 255

    DEFAULT_SESSION_DAYS = 30

    _password_hash = PasswordHash.recommended()

    def __init__(self, engine=None):
        self.engine = engine or default_engine

    @classmethod
    def _validate_password(cls, password: str) -> str:
        if not isinstance(password, str):
            raise ValueError("password must be a string.")

        if len(password) < cls.MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"password must be at least "
                f"{cls.MIN_PASSWORD_LENGTH} characters."
            )

        if len(password) > cls.MAX_PASSWORD_LENGTH:
            raise ValueError(
                f"password cannot exceed "
                f"{cls.MAX_PASSWORD_LENGTH} characters."
            )

        return password

    @classmethod
    def _normalize_identifier(cls, identifier: str) -> str:
        if not isinstance(identifier, str):
            raise ValueError("identifier must be a string.")

        normalized = identifier.strip().lower()

        if not normalized:
            raise ValueError("identifier cannot be empty.")

        if len(normalized) > cls.MAX_IDENTIFIER_LENGTH:
            raise ValueError(
                f"identifier cannot exceed "
                f"{cls.MAX_IDENTIFIER_LENGTH} characters."
            )

        return normalized

    @staticmethod
    def _utc_now_naive() -> datetime:
        return datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    @staticmethod
    def _generate_refresh_token() -> str:
        """
        Generate a high-entropy opaque refresh token.

        The plaintext value is returned only to the caller and is
        never persisted to the database.
        """
        return secrets.token_urlsafe(48)

    @staticmethod
    def _hash_refresh_token(refresh_token: str) -> str:
        """
        Hash an opaque refresh token for database persistence.

        Refresh tokens have high entropy, so a fast cryptographic
        hash is appropriate for storage; the raw token is never
        written to the database.
        """
        return hashlib.sha256(
            refresh_token.encode("utf-8")
        ).hexdigest()

    @classmethod
    def _verify_password(
        cls,
        password: str,
        password_hash: str,
    ) -> bool:
        try:
            return cls._password_hash.verify(
                password,
                password_hash,
            )
        except Exception:
            return False

    @classmethod
    def _dummy_password_hash(cls) -> str:
        """
        Generate a valid Argon2 hash for timing-equalized
        authentication of unknown identifiers.
        """
        return cls._password_hash.hash(
            "nova-dummy-password"
        )

    def register_password_user(
        self,
        identifier: str,
        password: str,
        display_name: str | None = None,
        user_id: str | None = None,
    ) -> tuple[User, AuthIdentity]:
        """
        Atomically create a NOVA User and local password identity.

        For the password provider, provider_subject stores the
        normalized login identifier. External providers will later
        use their provider-specific subject value.
        """
        normalized_identifier = self._normalize_identifier(
            identifier
        )
        validated_password = self._validate_password(
            password
        )

        now = self._utc_now_naive()

        with Session(self.engine) as session:
            try:
                user = User(
                    id=user_id,
                    display_name=display_name,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )

                identity = AuthIdentity(
                    user_id=None,
                    provider=self.PASSWORD_PROVIDER,
                    provider_subject=normalized_identifier,
                    password_hash=self._password_hash.hash(
                        validated_password
                    ),
                    created_at=now,
                    updated_at=now,
                )

                session.add(user)
                session.flush()

                identity.user_id = user.id

                session.add(identity)
                session.commit()

                session.refresh(user)
                session.refresh(identity)

                return user, identity

            except IntegrityError as exc:
                session.rollback()
                raise ValueError(
                    "A user or authentication identity already exists."
                ) from exc

    def authenticate_password(
        self,
        identifier: str,
        password: str,
    ) -> User | None:
        """
        Authenticate an active NOVA user using a local password.

        Unknown identifiers still execute an Argon2 verification
        against a dummy hash to reduce username/account timing
        differences.
        """
        normalized_identifier = self._normalize_identifier(
            identifier
        )
        validated_password = self._validate_password(
            password
        )

        with Session(self.engine) as session:
            identity = session.scalar(
                select(AuthIdentity)
                .where(
                    AuthIdentity.provider
                    == self.PASSWORD_PROVIDER,
                    AuthIdentity.provider_subject
                    == normalized_identifier,
                )
            )

            if identity is None:
                self._verify_password(
                    validated_password,
                    self._dummy_password_hash(),
                )
                return None

            if not identity.password_hash:
                return None

            user = session.get(
                User,
                identity.user_id,
            )

            if user is None or not user.is_active:
                self._verify_password(
                    validated_password,
                    identity.password_hash,
                )
                return None

            if not self._verify_password(
                validated_password,
                identity.password_hash,
            ):
                return None

            return user

    def create_session(
        self,
        user_id: str,
        session_days: int | None = None,
    ) -> tuple[UserSession, str]:
        """
        Create a durable authenticated session.

        Returns the persisted session and the raw refresh token.
        The raw refresh token must be delivered to the client but
        is never stored directly.
        """
        if not user_id or not str(user_id).strip():
            raise ValueError("user_id cannot be empty.")

        days = (
            self.DEFAULT_SESSION_DAYS
            if session_days is None
            else session_days
        )

        if days <= 0:
            raise ValueError(
                "session_days must be greater than zero."
            )

        now = self._utc_now_naive()
        expires_at = now + timedelta(days=days)

        refresh_token = self._generate_refresh_token()
        refresh_token_hash = self._hash_refresh_token(
            refresh_token
        )

        with Session(self.engine) as session:
            user = session.get(User, user_id)

            if user is None:
                raise ValueError("User not found.")

            if not user.is_active:
                raise ValueError("User is inactive.")

            user_session = UserSession(
                user_id=user.id,
                refresh_token_hash=refresh_token_hash,
                expires_at=expires_at,
                last_used_at=now,
                revoked_at=None,
                created_at=now,
                updated_at=now,
            )

            session.add(user_session)

            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ValueError(
                    "Could not create authentication session."
                ) from exc

            session.refresh(user_session)

            return user_session, refresh_token

    def rotate_session(
        self,
        refresh_token: str,
        session_days: int | None = None,
    ) -> tuple[UserSession, str]:
        """
        Atomically rotate a refresh token.

        The old token stops being valid after successful rotation.
        A concurrent reuse of the same old token cannot win a
        second update because the stored hash has already changed.
        """
        if not isinstance(refresh_token, str):
            raise ValueError("refresh_token must be a string.")

        if not refresh_token:
            raise ValueError("refresh_token cannot be empty.")

        old_hash = self._hash_refresh_token(
            refresh_token
        )

        days = (
            self.DEFAULT_SESSION_DAYS
            if session_days is None
            else session_days
        )

        if days <= 0:
            raise ValueError(
                "session_days must be greater than zero."
            )

        now = self._utc_now_naive()

        with Session(self.engine) as session:
            user_session = session.scalar(
                select(UserSession)
                .where(
                    UserSession.refresh_token_hash
                    == old_hash,
                )
                .with_for_update()
            )

            if user_session is None:
                history = session.scalar(
                    select(RefreshTokenHistory)
                    .where(
                        RefreshTokenHistory.token_hash
                        == old_hash,
                    )
                    .with_for_update()
                )

                if history is None:
                    raise ValueError(
                        "Invalid refresh token."
                    )

                replay_session = session.scalar(
                    select(UserSession)
                    .where(
                        UserSession.id
                        == history.session_id,
                    )
                    .with_for_update()
                )

                if replay_session is None:
                    raise ValueError(
                        "Invalid refresh token."
                    )

                if replay_session.revoked_at is None:
                    replay_session.revoked_at = now
                    replay_session.updated_at = now

                    session.commit()

                raise RefreshTokenReplayDetected(
                    user_id=replay_session.user_id,
                    session_id=replay_session.id,
                )

            if user_session.revoked_at is not None:
                raise ValueError("Session has been revoked.")

            if user_session.expires_at <= now:
                raise ValueError("Session has expired.")

            user = session.get(
                User,
                user_session.user_id,
            )

            if user is None or not user.is_active:
                raise ValueError("User is unavailable.")

            new_refresh_token = self._generate_refresh_token()
            new_hash = self._hash_refresh_token(
                new_refresh_token
            )
            new_expires_at = now + timedelta(days=days)

            history = RefreshTokenHistory(
                session_id=user_session.id,
                token_hash=old_hash,
                replaced_by_token_hash=new_hash,
                replaced_at=now,
            )

            session.add(history)

            user_session.refresh_token_hash = new_hash
            user_session.expires_at = new_expires_at
            user_session.last_used_at = now
            user_session.updated_at = now

            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ValueError(
                    "Refresh token was already rotated."
                ) from exc

            session.refresh(user_session)

            return user_session, new_refresh_token

    def revoke_session(
        self,
        session_id: str,
    ) -> bool:
        """
        Revoke one authenticated session.

        Returns False when the session does not exist or was
        already revoked.
        """
        if not session_id or not str(session_id).strip():
            raise ValueError("session_id cannot be empty.")

        now = self._utc_now_naive()

        with Session(self.engine) as session:
            user_session = session.get(
                UserSession,
                session_id,
            )

            if user_session is None:
                return False

            if user_session.revoked_at is not None:
                return False

            user_session.revoked_at = now
            user_session.updated_at = now

            session.commit()

            return True

    def get_session(
        self,
        session_id: str,
    ) -> UserSession | None:
        if not session_id or not str(session_id).strip():
            raise ValueError("session_id cannot be empty.")

        with Session(self.engine) as session:
            return session.get(
                UserSession,
                session_id,
            )

    def get_session_by_refresh_token(
        self,
        refresh_token: str,
    ) -> UserSession | None:
        if not isinstance(refresh_token, str):
            raise ValueError(
                "refresh_token must be a string."
            )

        if not refresh_token:
            raise ValueError(
                "refresh_token cannot be empty."
            )

        token_hash = self._hash_refresh_token(
            refresh_token
        )

        with Session(self.engine) as session:
            return session.scalar(
                select(UserSession)
                .where(
                    UserSession.refresh_token_hash
                    == token_hash,
                )
            )
