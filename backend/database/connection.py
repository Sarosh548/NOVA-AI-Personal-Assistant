import os

from sqlalchemy import create_engine, text

from config import get_database_settings


database_url = os.getenv("DATABASE_URL")

if not database_url:
    raise RuntimeError("DATABASE_URL is not set.")


def build_engine(
    database_url: str,
    connect_timeout_seconds: int,
):
    return create_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "connect_timeout": connect_timeout_seconds,
        },
    )


database_settings = get_database_settings()

engine = build_engine(
    database_url,
    database_settings.db_connect_timeout_seconds,
)


def test_connection() -> bool:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    return True
