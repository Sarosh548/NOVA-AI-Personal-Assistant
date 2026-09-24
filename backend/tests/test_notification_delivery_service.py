from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from models.notification_delivery import (
    NotificationDelivery,
)
from services.notification_delivery_service import (
    NotificationDeliveryService,
)


def build_runtime():
    db_engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    NotificationDelivery.__table__.create(
        bind=db_engine
    )

    return db_engine


def teardown_runtime(
    db_engine,
):
    NotificationDelivery.__table__.drop(
        bind=db_engine
    )
    db_engine.dispose()


def test_delivery_is_claimed_and_marked_sent():
    db_engine = build_runtime()

    try:
        service = NotificationDeliveryService(
            db_engine=db_engine
        )

        claimed = service.claim_delivery(
            user_id="user-001",
            channel="console",
            idempotency_key="delivery-1",
        )

        assert claimed["claimed"] is True

        assert service.mark_sent(
            delivery_id=claimed["delivery_id"],
            claim_token=claimed["claim_token"],
        )

        second = service.claim_delivery(
            user_id="user-001",
            channel="console",
            idempotency_key="delivery-1",
        )

        assert second["claimed"] is False
        assert second["reason"] == "already_sent"

    finally:
        teardown_runtime(
            db_engine
        )


def test_active_delivery_claim_blocks_duplicate():
    db_engine = build_runtime()

    try:
        service = NotificationDeliveryService(
            db_engine=db_engine,
            lease_seconds=60,
        )

        now = datetime(
            2026,
            9,
            21,
            10,
            0,
        )

        first = service.claim_delivery(
            user_id="user-001",
            channel="console",
            idempotency_key="delivery-2",
            now=now,
        )

        second = service.claim_delivery(
            user_id="user-001",
            channel="console",
            idempotency_key="delivery-2",
            now=now + timedelta(seconds=30),
        )

        assert second["claimed"] is False
        assert second["reason"] == "in_progress"
        assert (
            second["delivery_id"]
            == first["delivery_id"]
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_failed_delivery_can_be_reclaimed():
    db_engine = build_runtime()

    try:
        service = NotificationDeliveryService(
            db_engine=db_engine
        )

        first = service.claim_delivery(
            user_id="user-001",
            channel="console",
            idempotency_key="delivery-3",
        )

        assert service.mark_failed(
            delivery_id=first["delivery_id"],
            claim_token=first["claim_token"],
            error="temporary failure",
        )

        second = service.claim_delivery(
            user_id="user-001",
            channel="console",
            idempotency_key="delivery-3",
        )

        assert second["claimed"] is True
        assert second["reason"] == "reclaimed"
        assert second["attempt_count"] == 2

    finally:
        teardown_runtime(
            db_engine
        )


def test_notification_service_uses_durable_delivery_state():
    db_engine = build_runtime()

    try:
        class FakeChannel:
            def __init__(self):
                self.calls = 0

            def send(self, notification):
                self.calls += 1
                return True

        channel = FakeChannel()

        from services.notification_service import (
            NotificationService,
        )

        service = NotificationService(
            channel=channel,
            delivery_service=NotificationDeliveryService(
                db_engine=db_engine
            ),
        )

        first = service.notify(
            user_id="user-001",
            title="Test",
            body="Body",
            idempotency_key="delivery-4",
        )

        second = service.notify(
            user_id="user-001",
            title="Test",
            body="Body",
            idempotency_key="delivery-4",
        )

        assert first is True
        assert second is True
        assert channel.calls == 1

    finally:
        teardown_runtime(
            db_engine
        )


def _seed_delivery(
    db_engine,
    *,
    status: str,
    updated_at: datetime,
):
    with Session(db_engine) as session:
        delivery = NotificationDelivery(
            user_id="user-001",
            channel="console",
            idempotency_key=(
                f"retention-{status}-{updated_at.timestamp()}"
            ),
            status=status,
            attempt_count=1,
            claim_token=(
                "active-claim"
                if status == "processing"
                else None
            ),
            lease_until=(
                updated_at + timedelta(minutes=5)
                if status == "processing"
                else None
            ),
            sent_at=(
                updated_at
                if status == "sent"
                else None
            ),
            last_attempt_at=updated_at,
            last_error=(
                "failed"
                if status == "failed"
                else None
            ),
            created_at=updated_at,
            updated_at=updated_at,
        )
        session.add(delivery)
        session.commit()
        session.refresh(delivery)
        return delivery.id


def test_purge_expired_deliveries_removes_terminal_records():
    db_engine = build_runtime()

    try:
        service = NotificationDeliveryService(
            db_engine=db_engine,
            lease_seconds=60,
        )

        now = datetime(
            2026,
            9,
            24,
            10,
            0,
        )
        old = now - timedelta(days=31)
        recent = now - timedelta(days=1)

        sent_id = _seed_delivery(
            db_engine,
            status="sent",
            updated_at=old,
        )
        failed_id = _seed_delivery(
            db_engine,
            status="failed",
            updated_at=old,
        )
        processing_id = _seed_delivery(
            db_engine,
            status="processing",
            updated_at=old,
        )
        retained_id = _seed_delivery(
            db_engine,
            status="sent",
            updated_at=recent,
        )

        deleted = service.purge_expired_deliveries(
            retention_seconds=30 * 24 * 60 * 60,
            now=now,
        )

        assert deleted == 2

        with Session(db_engine) as session:
            remaining_ids = {
                delivery.id
                for delivery in session.scalars(
                    select(NotificationDelivery)
                )
            }

        assert sent_id not in remaining_ids
        assert failed_id not in remaining_ids
        assert processing_id in remaining_ids
        assert retained_id in remaining_ids

    finally:
        teardown_runtime(
            db_engine
        )


def test_purge_expired_deliveries_respects_batch_limit():
    db_engine = build_runtime()

    try:
        service = NotificationDeliveryService(
            db_engine=db_engine
        )

        now = datetime(
            2026,
            9,
            24,
            10,
            0,
        )
        old = now - timedelta(days=31)

        for index in range(3):
            _seed_delivery(
                db_engine,
                status="sent",
                updated_at=old - timedelta(
                    minutes=index
                ),
            )

        deleted = service.purge_expired_deliveries(
            retention_seconds=30 * 24 * 60 * 60,
            limit=2,
            now=now,
        )

        assert deleted == 2

        with Session(db_engine) as session:
            assert (
                session.query(
                    NotificationDelivery
                ).count()
                == 1
            )

    finally:
        teardown_runtime(
            db_engine
        )


def test_purge_expired_deliveries_rejects_invalid_configuration():
    db_engine = build_runtime()

    try:
        service = NotificationDeliveryService(
            db_engine=db_engine
        )

        with pytest.raises(
            ValueError,
            match="retention_seconds",
        ):
            service.purge_expired_deliveries(
                retention_seconds=0
            )

        with pytest.raises(
            ValueError,
            match="limit",
        ):
            service.purge_expired_deliveries(
                limit=0
            )

        with pytest.raises(
            ValueError,
            match="limit",
        ):
            service.purge_expired_deliveries(
                limit=5001
            )

    finally:
        teardown_runtime(
            db_engine
        )


def test_purge_expired_deliveries_normalizes_timezone_aware_now():
    db_engine = build_runtime()

    try:
        service = NotificationDeliveryService(
            db_engine=db_engine
        )

        naive_now = datetime(
            2026,
            9,
            24,
            10,
            0,
        )
        aware_now = naive_now.replace(
            tzinfo=timezone.utc
        )

        _seed_delivery(
            db_engine,
            status="failed",
            updated_at=naive_now - timedelta(
                days=31
            ),
        )

        assert service.purge_expired_deliveries(
            retention_seconds=30 * 24 * 60 * 60,
            now=aware_now,
        ) == 1

    finally:
        teardown_runtime(
            db_engine
        )
