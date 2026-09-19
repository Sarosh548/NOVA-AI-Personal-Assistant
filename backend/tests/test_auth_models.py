from datetime import datetime

from sqlalchemy import DateTime

from models.auth_identity import AuthIdentity
from models.user_session import UserSession

from models.auth_identity import AuthIdentity
from models.user_session import UserSession


def test_auth_identity_table_name():
    assert AuthIdentity.__tablename__ == "auth_identities"


def test_auth_identity_columns():
    expected = {
        "id",
        "user_id",
        "provider",
        "provider_subject",
        "password_hash",
        "created_at",
        "updated_at",
    }

    assert set(AuthIdentity.__table__.columns.keys()) == expected


def test_auth_identity_primary_key():
    column = AuthIdentity.__table__.c.id

    assert column.primary_key is True
    assert column.type.length == 100


def test_auth_identity_user_id_foreign_key():
    column = AuthIdentity.__table__.c.user_id

    assert column.nullable is False
    assert column.foreign_keys

    foreign_key = next(iter(column.foreign_keys))
    assert str(foreign_key.target_fullname) == "users.id"


def test_auth_identity_provider_is_required():
    column = AuthIdentity.__table__.c.provider

    assert column.nullable is False
    assert column.type.length == 50


def test_auth_identity_supports_password_and_external_provider_fields():
    assert AuthIdentity.__table__.c.password_hash.nullable is True
    assert AuthIdentity.__table__.c.provider_subject.nullable is True


def test_auth_identity_has_expected_unique_constraints():
    constraint_names = {
        constraint.name
        for constraint in AuthIdentity.__table__.constraints
        if constraint.name
    }

    assert "uq_auth_identities_user_provider" in constraint_names
    assert "uq_auth_identities_provider_subject" in constraint_names


def test_user_session_table_name():
    assert UserSession.__tablename__ == "sessions"


def test_user_session_columns():
    expected = {
        "id",
        "user_id",
        "refresh_token_hash",
        "expires_at",
        "last_used_at",
        "revoked_at",
        "created_at",
        "updated_at",
    }

    assert set(UserSession.__table__.columns.keys()) == expected


def test_user_session_primary_key():
    column = UserSession.__table__.c.id

    assert column.primary_key is True
    assert column.type.length == 100


def test_user_session_user_id_foreign_key():
    column = UserSession.__table__.c.user_id

    assert column.nullable is False
    assert column.foreign_keys

    foreign_key = next(iter(column.foreign_keys))
    assert str(foreign_key.target_fullname) == "users.id"


def test_user_session_refresh_token_hash_is_required_and_unique():
    column = UserSession.__table__.c.refresh_token_hash

    assert column.nullable is False
    assert column.unique is True
    assert column.type.length == 128


def test_user_session_expiration_is_required():
    column = UserSession.__table__.c.expires_at

    assert column.nullable is False
    assert isinstance(column.type, DateTime)


def test_user_session_lifecycle_fields_are_nullable():
    assert UserSession.__table__.c.last_used_at.nullable is True
    assert UserSession.__table__.c.revoked_at.nullable is True


def test_user_session_does_not_store_plain_refresh_token():
    columns = set(UserSession.__table__.columns.keys())

    assert "refresh_token" not in columns
    assert "access_token" not in columns
