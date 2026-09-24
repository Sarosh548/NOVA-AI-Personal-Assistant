from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from models.idempotency_record import (
    IdempotencyRecord,
)
from services.idempotency_service import (
    IdempotencyService,
)


def build_runtime():
    db_engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    IdempotencyRecord.__table__.create(
        bind=db_engine
    )

    return db_engine


def teardown_runtime(
    db_engine,
):
    IdempotencyRecord.__table__.drop(
        bind=db_engine
    )
    db_engine.dispose()


def _seed_record(
    db_engine,
    *,
    status: str,
    expires_at: datetime,
):
    with Session(db_engine) as session:
        record = IdempotencyRecord(
            user_id="user-001",
            endpoint="/chat",
            idempotency_key=(
                f"key-{status}-{expires_at.timestamp()}"
            ),
            request_hash=("a" * 64),
            status=status,
            response_status=200 if status == "completed" else None,
            response_body=(
                {"ok": True}
                if status == "completed"
                else None
            ),
            claim_token=(
                "active-claim"
                if status == "processing"
                else None
            ),
            lease_until=(
                expires_at
                if status == "processing"
                else None
            ),
            expires_at=expires_at,
            last_error=(
                "failed"
                if status == "failed"
                else None
            ),
            created_at=expires_at - timedelta(
                days=1
            ),
            updated_at=expires_at - timedelta(
                days=1
            ),
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


def test_purge_expired_records_removes_terminal_records():
    db_engine = build_runtime()

    try:
        service = IdempotencyService(
            db_engine=db_engine
        )

        now = datetime(
            2026,
            9,
            24,
            10,
            0,
        )

        completed_id = _seed_record(
            db_engine,
            status="completed",
            expires_at=now - timedelta(
                minutes=1
            ),
        )

        failed_id = _seed_record(
            db_engine,
            status="failed",
            expires_at=now - timedelta(
                minutes=1
            ),
        )

        active_id = _seed_record(
            db_engine,
            status="processing",
            expires_at=now - timedelta(
                minutes=1
            ),
        )

        retained_id = _seed_record(
            db_engine,
            status="completed",
            expires_at=now + timedelta(
                minutes=1
            ),
        )

        deleted = service.purge_expired_records(
            now=now
        )

        assert deleted == 2

        with Session(db_engine) as session:
            remaining_ids = {
                record.id
                for record in session.scalars(
                    select(IdempotencyRecord)
                )
            }

        assert completed_id not in remaining_ids
        assert failed_id not in remaining_ids
        assert active_id in remaining_ids
        assert retained_id in remaining_ids

    finally:
        teardown_runtime(
            db_engine
        )


def test_purge_expired_records_respects_batch_limit():
    db_engine = build_runtime()

    try:
        service = IdempotencyService(
            db_engine=db_engine
        )

        now = datetime(
            2026,
            9,
            24,
            10,
            0,
        )

        for index in range(3):
            _seed_record(
                db_engine,
                status="completed",
                expires_at=now - timedelta(
                    minutes=1 + index
                ),
            )

        deleted = service.purge_expired_records(
            limit=2,
            now=now,
        )

        assert deleted == 2

        with Session(db_engine) as session:
            assert (
                session.query(
                    IdempotencyRecord
                ).count()
                == 1
            )

    finally:
        teardown_runtime(
            db_engine
        )


def test_purge_expired_records_rejects_invalid_limit():
    db_engine = build_runtime()

    try:
        service = IdempotencyService(
            db_engine=db_engine
        )

        with pytest.raises(
            ValueError,
            match="limit",
        ):
            service.purge_expired_records(
                limit=0
            )

        with pytest.raises(
            ValueError,
            match="limit",
        ):
            service.purge_expired_records(
                limit=5001
            )

    finally:
        teardown_runtime(
            db_engine
        )


def test_purge_expired_records_normalizes_timezone_aware_now():
    db_engine = build_runtime()

    try:
        service = IdempotencyService(
            db_engine=db_engine
        )

        now = datetime(
            2026,
            9,
            24,
            10,
            0,
            tzinfo=timezone.utc,
        )

        _seed_record(
            db_engine,
            status="failed",
            expires_at=now.replace(
                tzinfo=None
            ) - timedelta(
                minutes=1
            ),
        )

        assert service.purge_expired_records(
            now=now
        ) == 1

    finally:
        teardown_runtime(
            db_engine
        )
