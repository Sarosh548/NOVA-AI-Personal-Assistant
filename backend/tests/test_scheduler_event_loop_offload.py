from __future__ import annotations

import pytest

from services.autonomous_workflow_scheduler import (
    AutonomousWorkflowScheduler,
)
from services.idempotency_cleanup_scheduler import (
    IdempotencyCleanupScheduler,
)
from services.proactive_activity_scheduler import (
    ProactiveActivityScheduler,
)
from services.reminder_scheduler import (
    ReminderScheduler,
)


@pytest.mark.asyncio
async def test_reminder_scheduler_offloads_blocking_cycle(monkeypatch):
    scheduler = ReminderScheduler()
    calls = []

    def sync_cycle():
        calls.append("sync")

    async def fake_to_thread(func, *args, **kwargs):
        calls.append((func.__name__, args, kwargs))
        return func(*args, **kwargs)

    scheduler._process_due_reminders_sync = sync_cycle
    monkeypatch.setattr(
        "services.reminder_scheduler.asyncio.to_thread",
        fake_to_thread,
    )

    await scheduler.process_due_reminders()

    assert calls == [
        ("sync_cycle", (), {}),
        "sync",
    ]


@pytest.mark.asyncio
async def test_autonomous_workflow_scheduler_offloads_blocking_cycle(
    monkeypatch,
):
    scheduler = AutonomousWorkflowScheduler()
    calls = []

    def sync_cycle():
        calls.append("sync")

    async def fake_to_thread(func, *args, **kwargs):
        calls.append((func.__name__, args, kwargs))
        return func(*args, **kwargs)

    scheduler._process_due_workflows_sync = sync_cycle
    monkeypatch.setattr(
        "services.autonomous_workflow_scheduler.asyncio.to_thread",
        fake_to_thread,
    )

    await scheduler.process_due_workflows()

    assert calls == [
        ("sync_cycle", (), {}),
        "sync",
    ]


@pytest.mark.asyncio
async def test_proactive_activity_scheduler_offloads_blocking_cycle(
    monkeypatch,
):
    scheduler = ProactiveActivityScheduler()
    calls = []

    def sync_cycle(*, now=None):
        calls.append(now)
        return ["done"]

    async def fake_to_thread(func, *args, **kwargs):
        calls.append((func.__name__, args, kwargs))
        return func(*args, **kwargs)

    scheduler._process_daily_activity_digests_sync = sync_cycle
    monkeypatch.setattr(
        "services.proactive_activity_scheduler.asyncio.to_thread",
        fake_to_thread,
    )

    result = await scheduler.process_daily_activity_digests(
        now="reference-now"
    )

    assert result == ["done"]
    assert calls == [
        ("sync_cycle", (), {"now": "reference-now"}),
        "reference-now",
    ]


@pytest.mark.asyncio
async def test_idempotency_cleanup_scheduler_offloads_blocking_cycle(
    monkeypatch,
):
    scheduler = IdempotencyCleanupScheduler()
    calls = []

    def sync_cycle():
        calls.append("sync")
        return 7

    async def fake_to_thread(func, *args, **kwargs):
        calls.append((func.__name__, args, kwargs))
        return func(*args, **kwargs)

    scheduler._process_expired_records_sync = sync_cycle
    monkeypatch.setattr(
        "services.idempotency_cleanup_scheduler.asyncio.to_thread",
        fake_to_thread,
    )

    result = await scheduler.process_expired_records()

    assert result == 7
    assert calls == [
        ("sync_cycle", (), {}),
        "sync",
    ]
