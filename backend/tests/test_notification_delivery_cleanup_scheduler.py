from __future__ import annotations

import pytest

from services.notification_delivery_cleanup_scheduler import (
    NotificationDeliveryCleanupScheduler,
)


class FakeNotificationDeliveryService:
    def __init__(self):
        self.calls = []

    def purge_expired_deliveries(
        self,
        *,
        retention_seconds,
        limit,
    ):
        self.calls.append(
            {
                "retention_seconds": retention_seconds,
                "limit": limit,
            }
        )
        return 3


@pytest.mark.asyncio
async def test_cleanup_scheduler_processes_one_batch():
    fake = FakeNotificationDeliveryService()

    scheduler = NotificationDeliveryCleanupScheduler(
        interval_seconds=10,
        retention_seconds=120,
        delivery_service=fake,
        batch_size=25,
    )

    assert scheduler.purge_expired_deliveries() == 3
    assert fake.calls == [
        {
            "retention_seconds": 120,
            "limit": 25,
        }
    ]


def test_cleanup_scheduler_rejects_invalid_configuration():
    with pytest.raises(
        ValueError,
        match="interval_seconds",
    ):
        NotificationDeliveryCleanupScheduler(
            interval_seconds=9
        )

    with pytest.raises(
        ValueError,
        match="retention_seconds",
    ):
        NotificationDeliveryCleanupScheduler(
            interval_seconds=10,
            retention_seconds=0,
        )

    with pytest.raises(
        ValueError,
        match="batch_size",
    ):
        NotificationDeliveryCleanupScheduler(
            interval_seconds=10,
            batch_size=0,
        )


@pytest.mark.asyncio
async def test_cleanup_scheduler_stops_after_one_cycle(
    monkeypatch,
):
    fake = FakeNotificationDeliveryService()

    scheduler = NotificationDeliveryCleanupScheduler(
        interval_seconds=10,
        retention_seconds=120,
        delivery_service=fake,
        batch_size=25,
    )

    async def stop_sleep(_seconds):
        scheduler.stop()

    monkeypatch.setattr(
        "services.notification_delivery_cleanup_scheduler.asyncio.sleep",
        stop_sleep,
    )

    await scheduler.run()

    assert fake.calls == [
        {
            "retention_seconds": 120,
            "limit": 25,
        }
    ]
    assert scheduler._running is False
