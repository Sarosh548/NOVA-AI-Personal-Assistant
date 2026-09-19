from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from jwt.exceptions import InvalidTokenError

from config import Settings, get_settings


class TokenService:
    """
    Issue and validate NOVA access tokens.

    Access tokens are short-lived signed JWTs. Refresh tokens are
    deliberately handled by AuthService and are not JWTs.
    """

    ACCESS_TOKEN_TYPE = "access"

    REQUIRED_CLAIMS = (
        "sub",
        "sid",
        "jti",
        "type",
        "iat",
        "exp",
        "iss",
        "aud",
    )

    def __init__(
        self,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc)

    @staticmethod
    def _validate_identifier(
        value: str,
        field_name: str,
    ) -> str:
        if not isinstance(value, str):
            raise ValueError(
                f"{field_name} must be a string."
            )

        normalized = value.strip()

        if not normalized:
            raise ValueError(
                f"{field_name} cannot be empty."
            )

        return normalized

    def create_access_token(
        self,
        user_id: str,
        session_id: str,
        now: datetime | None = None,
    ) -> str:
        """
        Create a short-lived access JWT for one authenticated
        NOVA user session.
        """
        normalized_user_id = self._validate_identifier(
            user_id,
            "user_id",
        )

        normalized_session_id = self._validate_identifier(
            session_id,
            "session_id",
        )

        issued_at = self._normalize_datetime(
            now or self._utc_now()
        )

        expires_at = (
            issued_at
            + timedelta(
                minutes=self.settings.auth_access_token_expire_minutes
            )
        )

        payload = {
            "sub": normalized_user_id,
            "sid": normalized_session_id,
            "jti": str(uuid4()),
            "type": self.ACCESS_TOKEN_TYPE,
            "iat": issued_at,
            "exp": expires_at,
            "iss": self.settings.auth_jwt_issuer,
            "aud": self.settings.auth_jwt_audience,
        }

        return jwt.encode(
            payload,
            self.settings.auth_jwt_secret_key,
            algorithm=self.settings.auth_jwt_algorithm,
        )

    def decode_access_token(
        self,
        token: str,
    ) -> dict[str, object]:
        """
        Validate an access token and return its claims.

        Signature, expiry, issuer, audience, required claims, and
        token type are all verified before claims are returned.
        """
        if not isinstance(token, str):
            raise ValueError(
                "token must be a string."
            )

        if not token.strip():
            raise ValueError(
                "token cannot be empty."
            )

        try:
            payload = jwt.decode(
                token,
                self.settings.auth_jwt_secret_key,
                algorithms=[
                    self.settings.auth_jwt_algorithm
                ],
                audience=self.settings.auth_jwt_audience,
                issuer=self.settings.auth_jwt_issuer,
                options={
                    "require": list(
                        self.REQUIRED_CLAIMS
                    )
                },
            )
        except InvalidTokenError as exc:
            raise ValueError(
                "Invalid access token."
            ) from exc

        if payload.get("type") != self.ACCESS_TOKEN_TYPE:
            raise ValueError(
                "Invalid token type."
            )

        return payload
