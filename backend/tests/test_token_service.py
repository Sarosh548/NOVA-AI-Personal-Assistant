from datetime import datetime, timedelta, timezone

import jwt
import pytest

from config import Settings
from services.token_service import TokenService


TEST_SECRET = (
    "test-secret-key-that-is-longer-than-32-characters"
)


def _settings(**overrides):
    values = {
        "auth_jwt_secret_key": TEST_SECRET,
        "auth_jwt_algorithm": "HS256",
        "auth_jwt_issuer": "nova-test",
        "auth_jwt_audience": "nova-client-test",
        "auth_access_token_expire_minutes": 10,
    }

    values.update(overrides)

    return Settings(**values)


def test_create_access_token_contains_expected_claims():
    service = TokenService(
        settings=_settings()
    )

    token = service.create_access_token(
        user_id="user-123",
        session_id="session-456",
    )

    claims = service.decode_access_token(token)

    assert claims["sub"] == "user-123"
    assert claims["sid"] == "session-456"
    assert claims["type"] == "access"
    assert claims["iss"] == "nova-test"
    assert claims["aud"] == "nova-client-test"
    assert claims["jti"]
    assert claims["iat"]
    assert claims["exp"]


def test_access_token_round_trip():
    service = TokenService(
        settings=_settings()
    )

    token = service.create_access_token(
        user_id="user-123",
        session_id="session-456",
    )

    first_claims = service.decode_access_token(token)
    second_claims = service.decode_access_token(token)

    assert first_claims == second_claims


def test_each_access_token_gets_unique_jti():
    service = TokenService(
        settings=_settings()
    )

    token_one = service.create_access_token(
        user_id="user-123",
        session_id="session-456",
    )
    token_two = service.create_access_token(
        user_id="user-123",
        session_id="session-456",
    )

    claims_one = service.decode_access_token(token_one)
    claims_two = service.decode_access_token(token_two)

    assert claims_one["jti"] != claims_two["jti"]


def test_access_token_uses_configured_expiration():
    issued_at = datetime.now(
        timezone.utc
    ).replace(
        microsecond=0
    )

    service = TokenService(
        settings=_settings(
            auth_access_token_expire_minutes=15
        )
    )

    token = service.create_access_token(
        user_id="user-123",
        session_id="session-456",
        now=issued_at,
    )

    claims = service.decode_access_token(token)

    assert claims["exp"] == (
        int(
            (
                issued_at
                + timedelta(minutes=15)
            ).timestamp()
        )
    )


def test_empty_user_id_is_rejected():
    service = TokenService(
        settings=_settings()
    )

    with pytest.raises(ValueError):
        service.create_access_token(
            user_id=" ",
            session_id="session-456",
        )


def test_empty_session_id_is_rejected():
    service = TokenService(
        settings=_settings()
    )

    with pytest.raises(ValueError):
        service.create_access_token(
            user_id="user-123",
            session_id=" ",
        )


def test_empty_token_is_rejected():
    service = TokenService(
        settings=_settings()
    )

    with pytest.raises(ValueError):
        service.decode_access_token(" ")


def test_wrong_secret_is_rejected():
    service = TokenService(
        settings=_settings()
    )

    token = service.create_access_token(
        user_id="user-123",
        session_id="session-456",
    )

    other_service = TokenService(
        settings=_settings(
            auth_jwt_secret_key=(
                "different-secret-key-that-is-longer-than-32-characters"
            )
        )
    )

    with pytest.raises(ValueError):
        other_service.decode_access_token(token)


def test_wrong_audience_is_rejected():
    service = TokenService(
        settings=_settings()
    )

    token = service.create_access_token(
        user_id="user-123",
        session_id="session-456",
    )

    other_service = TokenService(
        settings=_settings(
            auth_jwt_audience="different-client"
        )
    )

    with pytest.raises(ValueError):
        other_service.decode_access_token(token)


def test_wrong_issuer_is_rejected():
    service = TokenService(
        settings=_settings()
    )

    token = service.create_access_token(
        user_id="user-123",
        session_id="session-456",
    )

    other_service = TokenService(
        settings=_settings(
            auth_jwt_issuer="different-api"
        )
    )

    with pytest.raises(ValueError):
        other_service.decode_access_token(token)


def test_expired_token_is_rejected():
    issued_at = datetime.now(
        timezone.utc
    ) - timedelta(
        minutes=2
    )

    service = TokenService(
        settings=_settings(
            auth_access_token_expire_minutes=1
        )
    )

    token = service.create_access_token(
        user_id="user-123",
        session_id="session-456",
        now=issued_at,
    )

    with pytest.raises(ValueError):
        service.decode_access_token(token)


def test_wrong_algorithm_is_rejected():
    service = TokenService(
        settings=_settings()
    )

    token = jwt.encode(
        {
            "sub": "user-123",
            "sid": "session-456",
            "jti": "test-jti",
            "type": "access",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc)
            + timedelta(minutes=10),
            "iss": "nova-test",
            "aud": "nova-client-test",
        },
        TEST_SECRET,
        algorithm="HS384",
    )

    with pytest.raises(ValueError):
        service.decode_access_token(token)


def test_wrong_token_type_is_rejected():
    service = TokenService(
        settings=_settings()
    )

    issued_at = datetime.now(
        timezone.utc
    )

    token = jwt.encode(
        {
            "sub": "user-123",
            "sid": "session-456",
            "jti": "test-jti",
            "type": "refresh",
            "iat": issued_at,
            "exp": issued_at + timedelta(minutes=10),
            "iss": "nova-test",
            "aud": "nova-client-test",
        },
        TEST_SECRET,
        algorithm="HS256",
    )

    with pytest.raises(ValueError):
        service.decode_access_token(token)


def test_missing_required_claim_is_rejected():
    service = TokenService(
        settings=_settings()
    )

    issued_at = datetime.now(
        timezone.utc
    )

    token = jwt.encode(
        {
            "sub": "user-123",
            "sid": "session-456",
            "jti": "test-jti",
            "type": "access",
            "iat": issued_at,
            "exp": issued_at + timedelta(minutes=10),
            "iss": "nova-test",
        },
        TEST_SECRET,
        algorithm="HS256",
    )

    with pytest.raises(ValueError):
        service.decode_access_token(token)


def test_malformed_token_is_rejected():
    service = TokenService(
        settings=_settings()
    )

    with pytest.raises(ValueError):
        service.decode_access_token(
            "not-a-valid-jwt"
        )


def test_secret_must_be_at_least_32_characters():
    with pytest.raises(ValueError):
        Settings(
            auth_jwt_secret_key="too-short"
        )
