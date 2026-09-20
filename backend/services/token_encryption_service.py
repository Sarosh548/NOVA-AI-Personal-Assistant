from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class TokenEncryptionService:
    """
    Encrypt and decrypt external-provider credentials at rest.

    The encryption key is supplied by server-side configuration and
    is never persisted by NOVA.
    """

    def __init__(
        self,
        encryption_key: str | bytes | None,
    ):
        if encryption_key is None:
            raise ValueError(
                "External token encryption is not configured."
            )

        if isinstance(
            encryption_key,
            str,
        ):
            normalized_key = encryption_key.strip().encode(
                "utf-8"
            )
        elif isinstance(
            encryption_key,
            bytes,
        ):
            normalized_key = encryption_key.strip()
        else:
            raise ValueError(
                "External token encryption key must be text or bytes."
            )

        if not normalized_key:
            raise ValueError(
                "External token encryption key cannot be empty."
            )

        try:
            self._fernet = Fernet(
                normalized_key
            )
        except (
            ValueError,
            TypeError,
        ) as exc:
            raise ValueError(
                "External token encryption key is invalid."
            ) from exc

    def encrypt(
        self,
        value: str,
    ) -> str:
        if not isinstance(
            value,
            str,
        ):
            raise ValueError(
                "Token value must be a string."
            )

        if not value:
            raise ValueError(
                "Token value cannot be empty."
            )

        return self._fernet.encrypt(
            value.encode("utf-8")
        ).decode("utf-8")

    def decrypt(
        self,
        encrypted_value: str,
    ) -> str:
        if not isinstance(
            encrypted_value,
            str,
        ):
            raise ValueError(
                "Encrypted token value must be a string."
            )

        if not encrypted_value:
            raise ValueError(
                "Encrypted token value cannot be empty."
            )

        try:
            return self._fernet.decrypt(
                encrypted_value.encode("utf-8")
            ).decode("utf-8")
        except (
            InvalidToken,
            UnicodeDecodeError,
        ) as exc:
            raise ValueError(
                "Encrypted token value is invalid."
            ) from exc
