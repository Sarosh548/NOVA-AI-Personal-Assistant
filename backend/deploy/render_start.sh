#!/bin/sh
set -eu

# Render starts with an empty managed Postgres database. The first Alembic
# revision expects the historical messages and memories tables to exist, so
# initialize that idempotent baseline, then apply the normal migration chain.
python - <<'PY'
import os
from pathlib import Path

import psycopg

database_url = os.environ["DATABASE_URL"].replace(
    "postgresql+psycopg://",
    "postgresql://",
    1,
)
legacy_schema = Path("migrations/legacy_schema.sql").read_text(
    encoding="utf-8"
)
with psycopg.connect(database_url) as connection:
    connection.execute(legacy_schema)
PY

python -m alembic upgrade head
exec python -m uvicorn main:app --host 0.0.0.0 --port "${PORT:-10000}" --workers 1
