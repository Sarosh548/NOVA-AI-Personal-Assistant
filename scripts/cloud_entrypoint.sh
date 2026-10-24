#!/bin/sh
set -eu

# Hostless injects DATABASE_URL at runtime. Do not print the URL or credentials.
python - <<'PY'
import os
from pathlib import Path

import psycopg

raw_url = os.environ.get("DATABASE_URL", "").strip()
if not raw_url:
    raise SystemExit("DATABASE_URL is required for cloud startup.")

if raw_url.startswith("postgresql+psycopg://"):
    raw_url = "postgresql://" + raw_url.removeprefix("postgresql+psycopg://")
elif raw_url.startswith("postgres://"):
    raw_url = "postgresql://" + raw_url.removeprefix("postgres://")

with psycopg.connect(
    raw_url,
    connect_timeout=int(os.environ.get("DB_CONNECT_TIMEOUT_SECONDS", "5")),
) as connection:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.alembic_version')")
        migration_table_exists = cursor.fetchone()[0] is not None

    # The historical first Alembic revision expects these two baseline tables.
    # Initialize them only on a database without an Alembic version table.
    if not migration_table_exists:
        legacy_schema = Path("migrations/legacy_schema.sql").read_text(
            encoding="utf-8"
        )
        with connection.cursor() as cursor:
            cursor.execute(legacy_schema)
        connection.commit()
PY

python -m alembic upgrade head

port="${PORT:-8000}"
case "$port" in
  ''|*[!0-9]*)
    echo "PORT must be a numeric TCP port." >&2
    exit 1
    ;;
esac

exec python -m uvicorn main:app --host 0.0.0.0 --port "$port" --workers "${WEB_CONCURRENCY:-1}"
