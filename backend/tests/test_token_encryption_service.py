import pytest

from services.token_encryption_service import (
    TokenEncryptionService,
)


def test_token_encryption_round_trip():
    from cryptography.fernet import Fernet

    service = TokenEncryptionService(
        Fernet.generate_key()
    )

    encrypted = service.encrypt(
        "refresh-token-secret"
    )

    assert encrypted != (
        "refresh-token-secret"
    )

    assert service.decrypt(
        encrypted
    ) == "refresh-token-secret"


def test_token_encryption_rejects_invalid_key():
    with pytest.raises(
        ValueError,
        match="encryption key is invalid",
    ):
        TokenEncryptionService(
            "not-a-valid-fernet-key"
        )


def test_token_encryption_rejects_wrong_key():
    from cryptography.fernet import Fernet

    service = TokenEncryptionService(
        Fernet.generate_key()
    )

    other_service = TokenEncryptionService(
        Fernet.generate_key()
    )

    encrypted = service.encrypt(
        "secret"
    )

    with pytest.raises(
        ValueError,
        match="Encrypted token value is invalid",
    ):
        other_service.decrypt(
            encrypted
        )


def test_token_encryption_rejects_empty_values():
    from cryptography.fernet import Fernet

    service = TokenEncryptionService(
        Fernet.generate_key()
    )

    with pytest.raises(
        ValueError,
        match="Token value cannot be empty",
    ):
        service.encrypt("")

    with pytest.raises(
        ValueError,
        match="Encrypted token value cannot be empty",
    ):
        service.decrypt("")
