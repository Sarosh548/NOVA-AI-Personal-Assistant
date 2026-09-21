from datetime import datetime, timedelta

from sqlalchemy import create_engine
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
