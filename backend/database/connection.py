import os

from sqlalchemy import create_engine, text

database_url = os.getenv("DATABASE_URL")

if not database_url:
    raise RuntimeError("DATABASE_URL is not set.")

engine = create_engine(
    database_url,
    echo=False,
)


def test_connection() -> bool:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    return True