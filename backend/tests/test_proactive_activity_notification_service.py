from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.activity_digest_delivery import (
    ActivityDigestDelivery,
)
from services.proactive_activity_notification_service import (
    ProactiveActivityNotificationService,
)


def build_runtime():
    db_engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    ActivityDigestDelivery.__table__.create(
        bind=db_engine
    )

    return db_engine


def teardown_runtime(
    db_engine,
):
    ActivityDigestDelivery.__table__.drop(
        bind=db_engine
    )

    db_engine.dispose()


class FakeDigestService:
    def __init__(
        self,
        *,
        should_notify=True,
        timezone_name="Asia/Karachi",
    ):
        self.should_notify = should_notify
        self.timezone_name = timezone_name
        self.calls = []

    def build_daily_digest(
        self,
        *,
        user_id,
        now,
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "now": now,
            }
        )

        if not self.should_notify:
            return {
                "should_notify": False,
                "reason": "no_activity",
                "user_id": user_id,
                "notification_type": "activity",
                "title": None,
                "body": None,
                "metadata": {
                    "timezone": (
                        self.timezone_name
                    ),
                    "total_events": 0,
                },
            }

        return {
            "should_notify": True,
            "reason": "activity_available",
            "user_id": user_id,
            "notification_type": "activity",
            "title": (
                "NOVA daily activity update"
            ),
            "body": (
                "Aaj 3 activities hui hain."
            ),
            "metadata": {
                "timezone": (
                    self.timezone_name
                ),
                "total_events": 3,
                "important_event_count": 2,
            },
            "report": {
                "error": None,
            },
        }


class FakeNotificationService:
    def __init__(
        self,
        result=True,
    ):
        self.result = result
        self.notifications = []

    def notify(
        self,
        *,
        user_id,
        title,
        body,
        notification_type,
        metadata,
    ):
        self.notifications.append(
            {
                "user_id": user_id,
                "title": title,
                "body": body,
                "notification_type": (
                    notification_type
                ),
                "metadata": metadata,
            }
        )

        return self.result


def build_service(
    db_engine,
    *,
    digest_service=None,
    notification_service=None,
    lease_seconds=300,
):
    return ProactiveActivityNotificationService(
        db_engine=db_engine,
        activity_digest_service=(
            digest_service
            if digest_service is not None
            else FakeDigestService()
        ),
        notification_service=(
            notification_service
            if notification_service is not None
            else FakeNotificationService()
        ),
        lease_seconds=lease_seconds,
    )


def test_new_daily_digest_is_claimed():
    db_engine = build_runtime()

    try:
        service = build_service(
            db_engine
        )

        result = service.claim_daily_digest(
            user_id="user-001",
            digest_date=date(
                2026,
                9,
                18,
            ),
        )

        assert result["claimed"] is True
        assert result["reason"] == "claimed"
        assert (
            result["status"]
            == "processing"
        )
        assert (
            result["attempt_count"]
            == 1
        )
        assert result["claim_token"]
        assert result["delivery_key"] == (
            "nova:daily_activity:"
            "user-001:2026-09-18"
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_sent_digest_cannot_be_claimed_again():
    db_engine = build_runtime()

    try:
        service = build_service(
            db_engine
        )

        first = service.claim_daily_digest(
            user_id="user-001",
            digest_date=date(
                2026,
                9,
                18,
            ),
        )

        assert service.mark_sent(
            delivery_id=first["delivery_id"],
            claim_token=first["claim_token"],
        )

        second = service.claim_daily_digest(
            user_id="user-001",
            digest_date=date(
                2026,
                9,
                18,
            ),
        )

        assert second["claimed"] is False
        assert (
            second["reason"]
            == "already_sent"
        )
        assert second["status"] == "sent"

    finally:
        teardown_runtime(
            db_engine
        )


def test_active_processing_lease_blocks_duplicate_claim():
    db_engine = build_runtime()

    try:
        service = build_service(
            db_engine,
            lease_seconds=300,
        )

        now = datetime(
            2026,
            9,
            18,
            8,
            0,
        )

        first = service.claim_daily_digest(
            user_id="user-001",
            digest_date=date(
                2026,
                9,
                18,
            ),
            now=now,
        )

        second = service.claim_daily_digest(
            user_id="user-001",
            digest_date=date(
                2026,
                9,
                18,
            ),
            now=(
                now
                + timedelta(
                    seconds=30
                )
            ),
        )

        assert second["claimed"] is False
        assert (
            second["reason"]
            == "in_progress"
        )
        assert (
            second["delivery_id"]
            == first["delivery_id"]
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_expired_processing_lease_is_reclaimed():
    db_engine = build_runtime()

    try:
        service = build_service(
            db_engine,
            lease_seconds=60,
        )

        first_time = datetime(
            2026,
            9,
            18,
            8,
            0,
        )

        first = service.claim_daily_digest(
            user_id="user-001",
            digest_date=date(
                2026,
                9,
                18,
            ),
            now=first_time,
        )

        second = service.claim_daily_digest(
            user_id="user-001",
            digest_date=date(
                2026,
                9,
                18,
            ),
            now=(
                first_time
                + timedelta(
                    seconds=61
                )
            ),
        )

        assert second["claimed"] is True
        assert second["reason"] == "reclaimed"
        assert (
            second["delivery_id"]
            == first["delivery_id"]
        )
        assert (
            second["claim_token"]
            != first["claim_token"]
        )
        assert (
            second["attempt_count"]
            == 2
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_failed_delivery_can_be_retried():
    db_engine = build_runtime()

    try:
        service = build_service(
            db_engine
        )

        first = service.claim_daily_digest(
            user_id="user-001",
            digest_date=date(
                2026,
                9,
                18,
            ),
        )

        assert service.mark_failed(
            delivery_id=first["delivery_id"],
            claim_token=first["claim_token"],
            error="Temporary delivery failure.",
        )

        second = service.claim_daily_digest(
            user_id="user-001",
            digest_date=date(
                2026,
                9,
                18,
            ),
        )

        assert second["claimed"] is True
        assert second["attempt_count"] == 2
        assert (
            second["claim_token"]
            != first["claim_token"]
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_successful_daily_digest_is_delivered_and_persisted():
    db_engine = build_runtime()

    try:
        digest_service = FakeDigestService()
        notification_service = (
            FakeNotificationService(
                result=True
            )
        )

        service = build_service(
            db_engine,
            digest_service=digest_service,
            notification_service=(
                notification_service
            ),
        )

        now = datetime(
            2026,
            9,
            18,
            10,
            0,
            tzinfo=timezone.utc,
        )

        result = (
            service.deliver_daily_activity_digest(
                user_id="user-001",
                now=now,
            )
        )

        assert result["delivered"] is True
        assert result["skipped"] is False
        assert (
            result["reason"]
            == "delivered"
        )

        assert (
            len(
                notification_service.notifications
            )
            == 1
        )

        notification = (
            notification_service
            .notifications[0]
        )

        assert (
            notification["user_id"]
            == "user-001"
        )

        assert (
            notification["notification_type"]
            == "activity"
        )

        assert (
            notification["metadata"]
            ["delivery_key"]
            == (
                "nova:daily_activity:"
                "user-001:2026-09-18"
            )
        )

        delivery = service.get_delivery(
            user_id="user-001",
            digest_date=date(
                2026,
                9,
                18,
            ),
        )

        assert delivery is not None
        assert delivery["status"] == "sent"
        assert (
            delivery["attempt_count"]
            == 1
        )
        assert delivery["sent_at"] is not None

        # Second call on the same local day is idempotent.
        second = (
            service.deliver_daily_activity_digest(
                user_id="user-001",
                now=now,
            )
        )

        assert second["delivered"] is False
        assert second["skipped"] is True
        assert (
            second["reason"]
            == "already_sent"
        )

        assert (
            len(
                notification_service.notifications
            )
            == 1
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_failed_notification_is_persisted_for_retry():
    db_engine = build_runtime()

    try:
        notification_service = (
            FakeNotificationService(
                result=False
            )
        )

        service = build_service(
            db_engine,
            notification_service=(
                notification_service
            ),
        )

        result = (
            service.deliver_daily_activity_digest(
                user_id="user-001",
                now=datetime(
                    2026,
                    9,
                    18,
                    10,
                    0,
                    tzinfo=timezone.utc,
                ),
            )
        )

        assert result["delivered"] is False
        assert result["skipped"] is False
        assert (
            result["reason"]
            == "notification_failed"
        )

        delivery = service.get_delivery(
            user_id="user-001",
            digest_date=date(
                2026,
                9,
                18,
            ),
        )

        assert delivery is not None
        assert delivery["status"] == "failed"
        assert (
            delivery["last_error"]
            == (
                "Notification service "
                "reported delivery failure."
            )
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_no_activity_does_not_create_delivery_record():
    db_engine = build_runtime()

    try:
        service = build_service(
            db_engine,
            digest_service=FakeDigestService(
                should_notify=False
            ),
        )

        result = (
            service.deliver_daily_activity_digest(
                user_id="user-001",
            )
        )

        assert result["delivered"] is False
        assert result["skipped"] is True
        assert (
            result["reason"]
            == "no_activity"
        )

        delivery = service.get_delivery(
            user_id="user-001",
            digest_date=date(
                2026,
                9,
                18,
            ),
        )

        assert delivery is None

    finally:
        teardown_runtime(
            db_engine
        )


def test_service_rejects_invalid_lease():
    db_engine = build_runtime()

    try:
        try:
            ProactiveActivityNotificationService(
                db_engine=db_engine,
                lease_seconds=0,
            )

            raise AssertionError(
                "Expected ValueError."
            )

        except ValueError as exc:
            assert (
                str(exc)
                == (
                    "lease_seconds must be at least 1"
                )
            )

    finally:
        teardown_runtime(
            db_engine
        )