from uuid import UUID

from sqlalchemy import inspect

from models.user import (
    User,
    _generate_user_id,
)


def test_user_model_has_expected_table_name():
    assert User.__tablename__ == "users"


def test_user_model_has_expected_columns():
    mapper = inspect(User)

    assert {
        column.key
        for column in mapper.columns
    } == {
        "id",
        "display_name",
        "is_active",
        "created_at",
        "updated_at",
    }


def test_user_id_is_primary_key_and_string_based():
    mapper = inspect(User)

    user_id_column = mapper.columns["id"]

    assert user_id_column.primary_key is True
    assert user_id_column.type.length == 100


def test_user_id_generator_returns_uuid_string():
    first = _generate_user_id()
    second = _generate_user_id()

    assert first != second

    UUID(first)
    UUID(second)


def test_user_active_state_is_non_nullable():
    mapper = inspect(User)

    is_active_column = mapper.columns[
        "is_active"
    ]

    assert is_active_column.nullable is False


def test_user_identity_does_not_store_authentication_credentials():
    mapper = inspect(User)

    assert "password_hash" not in {
        column.key
        for column in mapper.columns
    }

    assert "provider" not in {
        column.key
        for column in mapper.columns
    }
