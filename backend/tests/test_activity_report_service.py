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

        # Previous UTC day but still outside today's
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

        assert (
            report["total_events"]
            == 3
        )

        assert (
            report["successful_count"]
            == 1
        )

        assert (
            report["pending_count"]
            == 1
        )

        assert (
            report["failed_count"]
            == 1
        )

        assert (
            report["blocked_count"]
            == 0
        )

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

        assert (
            report["total_events"]
            == 1
        )

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

        assert (
            report["total_events"]
            == 0
        )

        assert (
            report["report_text"]
            == (
                "Aaj abhi koi NOVA activity record nahi hui."
            )
        )

        assert (
            report["recent_events"]
            == []
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

        assert (
            report["partial_count"]
            == 1
        )

        assert (
            report["blocked_count"]
            == 1
        )

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