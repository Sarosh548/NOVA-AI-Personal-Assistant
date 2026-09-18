from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.activity_event import ActivityEvent
from services.activity_event_service import (
    ActivityEventService,
)
from services.activity_report_service import (
    ActivityReportService,
)


def build_runtime():
    db_engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    ActivityEvent.__table__.create(
        bind=db_engine
    )

    event_service = ActivityEventService(
        db_engine=db_engine
    )

    report_service = ActivityReportService(
        activity_event_service=event_service,
    )

    return (
        db_engine,
        event_service,
        report_service,
    )


def teardown_runtime(
    db_engine,
):
    ActivityEvent.__table__.drop(
        bind=db_engine
    )

    db_engine.dispose()


def test_local_day_window_uses_asia_karachi():
    (
        db_engine,
        event_service,
        report_service,
    ) = build_runtime()

    try:
        # 20:00 UTC on September 18 is 01:00
        # on September 19 in Asia/Karachi.
        now = datetime(
            2026,
            9,
            18,
            20,
            0,
            0,
            tzinfo=timezone.utc,
        )

        start, end = (
            report_service.get_local_day_window(
                now=now
            )
        )

        assert start == datetime(
            2026,
            9,
            18,
            19,
            0,
            0,
        )

        assert end == datetime(
            2026,
            9,
            19,
            19,
            0,
            0,
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_daily_report_aggregates_current_local_day():
    (
        db_engine,
        event_service,
        report_service,
    ) = build_runtime()

    try:
        now = datetime(
            2026,
            9,
            18,
            12,
            0,
            0,
            tzinfo=timezone.utc,
        )

        event_service.record_event(
            user_id="user-001",
            event_type="workflow_completed",
            source="workflow",
            title="Completed",
            summary="Workflow completed.",
            status="success",
            created_at=datetime(
                2026,
                9,
                18,
                5,
                0,
                0,
            ),
        )

        event_service.record_event(
            user_id="user-001",
            event_type="workflow_scheduled",
            source="workflow",
            title="Scheduled",
            summary="Workflow scheduled.",
            status="pending",
            created_at=datetime(
                2026,
                9,
                18,
                8,
                0,
                0,
            ),
        )

        event_service.record_event(
            user_id="user-001",
            event_type="workflow_failed",
            source="workflow",
            title="Failed",
            summary="Workflow failed.",
            status="failed",
            created_at=datetime(
                2026,
                9,
                18,
                10,
                0,
                0,
            ),
        )

        # Previous UTC day and outside today's
        # Asia/Karachi local reporting window.
        event_service.record_event(
            user_id="user-001",
            event_type="old_event",
            source="test",
            title="Old",
            summary="Old event.",
            status="success",
            created_at=datetime(
                2026,
                9,
                17,
                18,
                59,
                59,
            ),
        )

        report = report_service.get_daily_report(
            user_id="user-001",
            now=now,
        )

        assert report["total_events"] == 3

        assert report["successful_count"] == 1

        assert report["pending_count"] == 1

        assert report["failed_count"] == 1

        assert report["blocked_count"] == 0

        assert (
            report["event_type_counts"][
                "workflow_completed"
            ]
            == 1
        )

        assert (
            report["event_type_counts"][
                "workflow_scheduled"
            ]
            == 1
        )

        assert (
            report["event_type_counts"][
                "workflow_failed"
            ]
            == 1
        )

        assert (
            report["important_event_count"]
            == 3
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_daily_report_is_user_scoped():
    (
        db_engine,
        event_service,
        report_service,
    ) = build_runtime()

    try:
        now = datetime(
            2026,
            9,
            18,
            12,
            0,
            0,
            tzinfo=timezone.utc,
        )

        event_service.record_event(
            user_id="user-001",
            event_type="workflow_completed",
            source="workflow",
            title="User one",
            summary="Done.",
            status="success",
            created_at=datetime(
                2026,
                9,
                18,
                5,
                0,
                0,
            ),
        )

        event_service.record_event(
            user_id="user-002",
            event_type="workflow_completed",
            source="workflow",
            title="User two",
            summary="Done.",
            status="success",
            created_at=datetime(
                2026,
                9,
                18,
                6,
                0,
                0,
            ),
        )

        report = report_service.get_daily_report(
            user_id="user-001",
            now=now,
        )

        assert report["total_events"] == 1

        assert (
            report["recent_events"][0][
                "user_id"
            ]
            == "user-001"
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_daily_report_recent_events_are_newest_first():
    (
        db_engine,
        event_service,
        report_service,
    ) = build_runtime()

    try:
        now = datetime(
            2026,
            9,
            18,
            12,
            0,
            0,
            tzinfo=timezone.utc,
        )

        event_service.record_event(
            user_id="user-001",
            event_type="older",
            source="test",
            title="Older",
            summary="Older event.",
            created_at=datetime(
                2026,
                9,
                18,
                5,
                0,
                0,
            ),
        )

        event_service.record_event(
            user_id="user-001",
            event_type="newer",
            source="test",
            title="Newer",
            summary="Newer event.",
            created_at=datetime(
                2026,
                9,
                18,
                6,
                0,
                0,
            ),
        )

        report = report_service.get_daily_report(
            user_id="user-001",
            now=now,
            recent_limit=1,
        )

        assert (
            len(
                report["recent_events"]
            )
            == 1
        )

        assert (
            report["recent_events"][0][
                "event_type"
            ]
            == "newer"
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_empty_daily_report():
    (
        db_engine,
        event_service,
        report_service,
    ) = build_runtime()

    try:
        now = datetime(
            2026,
            9,
            18,
            12,
            0,
            0,
            tzinfo=timezone.utc,
        )

        report = report_service.get_daily_report(
            user_id="user-001",
            now=now,
        )

        assert report["total_events"] == 0

        assert (
            report["report_text"]
            == (
                "Aaj abhi koi NOVA activity record nahi hui."
            )
        )

        assert report["recent_events"] == []

        assert report["important_events"] == []

        assert (
            report["important_event_count"]
            == 0
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_daily_report_counts_partial_and_blocked_events():
    (
        db_engine,
        event_service,
        report_service,
    ) = build_runtime()

    try:
        now = datetime(
            2026,
            9,
            18,
            12,
            0,
            0,
            tzinfo=timezone.utc,
        )

        event_service.record_event(
            user_id="user-001",
            event_type="workflow_partial",
            source="workflow",
            title="Partial",
            summary="Partial workflow.",
            status="partial",
            created_at=datetime(
                2026,
                9,
                18,
                5,
                0,
                0,
            ),
        )

        event_service.record_event(
            user_id="user-001",
            event_type="workflow_blocked",
            source="workflow",
            title="Blocked",
            summary="Blocked workflow.",
            status="blocked",
            created_at=datetime(
                2026,
                9,
                18,
                6,
                0,
                0,
            ),
        )

        report = report_service.get_daily_report(
            user_id="user-001",
            now=now,
        )

        assert report["partial_count"] == 1

        assert report["blocked_count"] == 1

        assert (
            "1 partially complete hui."
            in report["report_text"]
        )

        assert (
            "1 blocked hain."
            in report["report_text"]
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_invalid_timezone_is_rejected():
    event_service = ActivityEventService()

    try:
        ActivityReportService(
            activity_event_service=event_service,
            timezone_name="Invalid/Timezone",
        )

        raise AssertionError(
            "Invalid timezone should have raised ValueError."
        )

    except ValueError as exc:
        assert (
            "Invalid report timezone"
            in str(exc)
        )


def test_failed_event_is_prioritized_over_success():
    (
        db_engine,
        event_service,
        report_service,
    ) = build_runtime()

    try:
        now = datetime(
            2026,
            9,
            18,
            12,
            0,
            0,
            tzinfo=timezone.utc,
        )

        event_service.record_event(
            user_id="user-001",
            event_type="task_complete",
            source="tool_router",
            title="Task completed",
            summary="A task was completed.",
            status="success",
            metadata={
                "tool": "task",
                "action": "complete",
                "entity_id": 10,
            },
            created_at=datetime(
                2026,
                9,
                18,
                10,
                0,
                0,
            ),
        )

        event_service.record_event(
            user_id="user-001",
            event_type="reminder_delivery_failed",
            source="reminder_scheduler",
            title="Reminder failed",
            summary="Reminder delivery failed.",
            status="failed",
            metadata={
                "reminder_id": 20,
            },
            created_at=datetime(
                2026,
                9,
                18,
                9,
                0,
                0,
            ),
        )

        report = report_service.get_daily_report(
            user_id="user-001",
            now=now,
        )

        assert (
            report["important_events"][0][
                "event_type"
            ]
            == "reminder_delivery_failed"
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_latest_task_event_replaces_older_task_highlight():
    (
        db_engine,
        event_service,
        report_service,
    ) = build_runtime()

    try:
        now = datetime(
            2026,
            9,
            18,
            12,
            0,
            0,
            tzinfo=timezone.utc,
        )

        event_service.record_event(
            user_id="user-001",
            event_type="task_create",
            source="tool_router",
            title="Task created",
            summary="Task was created.",
            status="success",
            metadata={
                "tool": "task",
                "action": "create",
                "entity_id": 101,
            },
            created_at=datetime(
                2026,
                9,
                18,
                5,
                0,
                0,
            ),
        )

        event_service.record_event(
            user_id="user-001",
            event_type="task_complete",
            source="tool_router",
            title="Task completed",
            summary="Task was completed.",
            status="success",
            metadata={
                "tool": "task",
                "action": "complete",
                "entity_id": 101,
            },
            created_at=datetime(
                2026,
                9,
                18,
                8,
                0,
                0,
            ),
        )

        report = report_service.get_daily_report(
            user_id="user-001",
            now=now,
        )

        assert (
            report["important_event_count"]
            == 1
        )

        assert (
            report["important_events"][0][
                "event_type"
            ]
            == "task_complete"
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_terminal_workflow_suppresses_schedule_highlight():
    (
        db_engine,
        event_service,
        report_service,
    ) = build_runtime()

    try:
        now = datetime(
            2026,
            9,
            18,
            12,
            0,
            0,
            tzinfo=timezone.utc,
        )

        workflow_id = 900

        event_service.record_event(
            user_id="user-001",
            workflow_id=workflow_id,
            event_type="workflow_scheduled",
            source="autonomous_workflow",
            title="Workflow scheduled",
            summary="Workflow scheduled.",
            status="pending",
            metadata={
                "workflow_id": workflow_id,
            },
            created_at=datetime(
                2026,
                9,
                18,
                5,
                0,
                0,
            ),
        )

        event_service.record_event(
            user_id="user-001",
            workflow_id=workflow_id,
            event_type="workflow_completed",
            source="autonomous_workflow",
            title="Workflow completed",
            summary="Workflow completed.",
            status="success",
            metadata={
                "workflow_id": workflow_id,
                "status": "completed",
            },
            created_at=datetime(
                2026,
                9,
                18,
                6,
                0,
                0,
            ),
        )

        report = report_service.get_daily_report(
            user_id="user-001",
            now=now,
        )

        highlight_types = [
            event["event_type"]
            for event in report[
                "important_events"
            ]
        ]

        assert (
            "workflow_completed"
            in highlight_types
        )

        assert (
            "workflow_scheduled"
            not in highlight_types
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_highlight_limit_is_respected():
    (
        db_engine,
        event_service,
        report_service,
    ) = build_runtime()

    try:
        now = datetime(
            2026,
            9,
            18,
            12,
            0,
            0,
            tzinfo=timezone.utc,
        )

        for index in range(1, 8):
            event_service.record_event(
                user_id="user-001",
                event_type=(
                    f"workflow_failed_{index}"
                ),
                source="workflow",
                title=f"Failed {index}",
                summary=f"Failure {index}.",
                status="failed",
                created_at=datetime(
                    2026,
                    9,
                    18,
                    4,
                    index,
                    0,
                ),
            )

        report = report_service.get_daily_report(
            user_id="user-001",
            now=now,
            highlight_limit=3,
        )

        assert (
            report["important_event_count"]
            == 3
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_daily_report_supports_per_user_timezone_override():
    (
        db_engine,
        event_service,
        report_service,
    ) = build_runtime()

    try:
        now = datetime(
            2026,
            9,
            18,
            12,
            0,
            0,
            tzinfo=timezone.utc,
        )

        # 08:00 UTC = 04:00 New York on Sep 18.
        event_service.record_event(
            user_id="user-ny",
            event_type="task_created",
            source="tool_router",
            title="New York task",
            summary="Task created.",
            status="success",
            created_at=datetime(
                2026,
                9,
                18,
                8,
                0,
                0,
            ),
        )

        report = report_service.get_daily_report(
            user_id="user-ny",
            now=now,
            timezone_name="America/New_York",
        )

        assert (
            report["timezone"]
            == "America/New_York"
        )

        assert (
            report["window_start_utc"]
            == datetime(
                2026,
                9,
                18,
                4,
                0,
                0,
            )
        )

        assert (
            report["window_end_utc"]
            == datetime(
                2026,
                9,
                19,
                4,
                0,
                0,
            )
        )

        assert report["total_events"] == 1

    finally:
        teardown_runtime(
            db_engine
        )


def test_daily_report_handles_dst_transition():
    (
        db_engine,
        event_service,
        report_service,
    ) = build_runtime()

    try:
        now = datetime(
            2026,
            11,
            1,
            12,
            0,
            0,
            tzinfo=timezone.utc,
        )

        start, end = (
            report_service.get_local_day_window(
                now=now,
                timezone_name="America/New_York",
            )
        )

        assert start == datetime(
            2026,
            11,
            1,
            4,
            0,
            0,
        )

        assert end == datetime(
            2026,
            11,
            2,
            5,
            0,
            0,
        )

    finally:
        teardown_runtime(
            db_engine
        )