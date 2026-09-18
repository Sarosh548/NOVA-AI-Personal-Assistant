from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.autonomous_workflow_service import (
    AutonomousWorkflowService,
)


class FakeWorkflowService:
    def __init__(self):
        self.calls = []

    def create_workflow(self, **kwargs):
        self.calls.append(kwargs)

        return {
            "id": 123,
            **kwargs,
        }


def fixed_now() -> datetime:
    return datetime(
        2026,
        9,
        18,
        5,
        0,
        0,
        tzinfo=timezone.utc,
    )


def build_service() -> tuple[
    AutonomousWorkflowService,
    FakeWorkflowService,
]:
    fake_workflow_service = FakeWorkflowService()

    service = AutonomousWorkflowService(
        workflow_service=fake_workflow_service,
    )

    service._utc_now = staticmethod(
        fixed_now
    )

    return service, fake_workflow_service


def test_create_scheduled_workflow_persists_autonomous_pending_workflow():
    service, fake_workflow_service = build_service()

    scheduled_at = datetime(
        2026,
        9,
        18,
        10,
        0,
        0,
        tzinfo=timezone.utc,
    )

    result = service.create_scheduled_workflow(
        user_id="user-001",
        conversation_id=42,
        plan={
            "requires_tool": True,
            "execution_mode": "autonomous",
        },
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "create",
                "data": {
                    "title": "Prepare report",
                },
            }
        ],
        scheduled_at=scheduled_at,
        idempotency_key="schedule-001",
    )

    assert result["id"] == 123

    assert len(
        fake_workflow_service.calls
    ) == 1

    call = fake_workflow_service.calls[0]

    assert call["user_id"] == "user-001"
    assert call["conversation_id"] == 42
    assert call["execution_mode"] == "autonomous"
    assert call["status"] == "pending"
    assert call["scheduled_at"] == datetime(
        2026,
        9,
        18,
        10,
        0,
        0,
    )
    assert call["idempotency_key"] == "schedule-001"


def test_timezone_aware_datetime_is_normalized_to_utc():
    service, fake_workflow_service = build_service()

    scheduled_at = datetime(
        2026,
        9,
        18,
        15,
        0,
        0,
        tzinfo=timezone(
            timedelta(hours=5)
        ),
    )

    service.create_scheduled_workflow(
        user_id="user-001",
        conversation_id=None,
        plan={},
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "create",
                "data": {},
            }
        ],
        scheduled_at=scheduled_at,
    )

    call = fake_workflow_service.calls[0]

    assert call["scheduled_at"] == datetime(
        2026,
        9,
        18,
        10,
        0,
        0,
    )


def test_naive_datetime_is_rejected():
    service, fake_workflow_service = build_service()

    scheduled_at = datetime(
        2026,
        9,
        18,
        10,
        0,
        0,
    )

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        service.create_scheduled_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={},
            steps=[],
            scheduled_at=scheduled_at,
        )

    assert (
        fake_workflow_service.calls
        == []
    )


def test_past_datetime_is_rejected():
    service, fake_workflow_service = build_service()

    scheduled_at = datetime(
        2026,
        9,
        18,
        4,
        59,
        59,
        tzinfo=timezone.utc,
    )

    with pytest.raises(
        ValueError,
        match="future",
    ):
        service.create_scheduled_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={},
            steps=[],
            scheduled_at=scheduled_at,
        )

    assert (
        fake_workflow_service.calls
        == []
    )


def test_current_datetime_is_rejected():
    service, fake_workflow_service = build_service()

    scheduled_at = fixed_now()

    with pytest.raises(
        ValueError,
        match="future",
    ):
        service.create_scheduled_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={},
            steps=[],
            scheduled_at=scheduled_at,
        )

    assert (
        fake_workflow_service.calls
        == []
    )


def test_invalid_user_id_is_rejected():
    service, fake_workflow_service = build_service()

    scheduled_at = fixed_now() + timedelta(
        hours=1
    )

    with pytest.raises(
        ValueError,
        match="user_id",
    ):
        service.create_scheduled_workflow(
            user_id="   ",
            conversation_id=None,
            plan={},
            steps=[],
            scheduled_at=scheduled_at,
        )

    assert (
        fake_workflow_service.calls
        == []
    )


def test_invalid_plan_is_rejected():
    service, fake_workflow_service = build_service()

    scheduled_at = fixed_now() + timedelta(
        hours=1
    )

    with pytest.raises(
        ValueError,
        match="plan",
    ):
        service.create_scheduled_workflow(
            user_id="user-001",
            conversation_id=None,
            plan=[],
            steps=[],
            scheduled_at=scheduled_at,
        )

    assert (
        fake_workflow_service.calls
        == []
    )


def test_invalid_steps_are_rejected():
    service, fake_workflow_service = build_service()

    scheduled_at = fixed_now() + timedelta(
        hours=1
    )

    with pytest.raises(
        ValueError,
        match="steps",
    ):
        service.create_scheduled_workflow(
            user_id="user-001",
            conversation_id=None,
            plan={},
            steps={},
            scheduled_at=scheduled_at,
        )

    assert (
        fake_workflow_service.calls
        == []
    )