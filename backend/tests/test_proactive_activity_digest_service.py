from datetime import datetime, timezone

import pytest

from services.proactive_activity_digest_service import (
    ProactiveActivityDigestService,
)


class FakeActivityReportService:
    def __init__(
        self,
        report,
    ):
        self.report = report
        self.calls = []

    def get_daily_report(
        self,
        *,
        user_id,
        now,
        highlight_limit,
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "now": now,
                "highlight_limit": (
                    highlight_limit
                ),
            }
        )

        return dict(
            self.report
        )


def base_report(
    *,
    total_events=3,
    error=None,
):
    return {
        "user_id": "user-001",
        "timezone": "Asia/Karachi",
        "total_events": total_events,
        "status_counts": {
            "success": 2,
            "pending": 1,
        },
        "event_type_counts": {
            "task_created": 1,
            "workflow_completed": 2,
        },
        "successful_count": 2,
        "pending_count": 1,
        "partial_count": 0,
        "failed_count": 0,
        "blocked_count": 0,
        "important_event_count": 2,
        "important_events": [
            {
                "id": 3,
                "event_type": "workflow_completed",
                "status": "success",
                "title": "Workflow completed",
                "summary": (
                    "Daily workflow completed."
                ),
            },
            {
                "id": 2,
                "event_type": "task_created",
                "status": "success",
                "title": "Task created",
                "summary": (
                    "Daily planning task created."
                ),
            },
        ],
        "recent_events": [],
        "report_text": (
            "Aaj 3 activities hui hain. "
            "2 successfully complete hui hain "
            "aur 1 activity pending hai."
        ),
        "error": error,
    }


def test_build_daily_digest_creates_notification_payload():
    report_service = (
        FakeActivityReportService(
            base_report()
        )
    )

    service = ProactiveActivityDigestService(
        activity_report_service=report_service,
        highlight_limit=5,
    )

    now = datetime(
        2026,
        9,
        18,
        12,
        0,
        tzinfo=timezone.utc,
    )

    digest = service.build_daily_digest(
        user_id="user-001",
        now=now,
    )

    assert digest["should_notify"] is True
    assert (
        digest["reason"]
        == "activity_available"
    )
    assert digest["user_id"] == "user-001"
    assert (
        digest["notification_type"]
        == "activity"
    )
    assert (
        digest["title"]
        == "NOVA daily activity update"
    )

    assert (
        "Aaj 3 activities hui hain."
        in digest["body"]
    )

    assert (
        "Workflow completed: "
        "Daily workflow completed."
        in digest["body"]
    )

    assert (
        "Task created: "
        "Daily planning task created."
        in digest["body"]
    )

    assert digest["metadata"] == {
        "timezone": "Asia/Karachi",
        "total_events": 3,
        "important_event_count": 2,
        "successful_count": 2,
        "pending_count": 1,
        "partial_count": 0,
        "failed_count": 0,
        "blocked_count": 0,
    }

    assert report_service.calls == [
        {
            "user_id": "user-001",
            "now": now,
            "highlight_limit": 5,
        }
    ]


def test_build_daily_digest_does_not_notify_when_no_activity():
    report_service = (
        FakeActivityReportService(
            base_report(
                total_events=0,
            )
        )
    )

    service = ProactiveActivityDigestService(
        activity_report_service=report_service,
    )

    digest = service.build_daily_digest(
        user_id="user-001",
    )

    assert digest["should_notify"] is False
    assert (
        digest["reason"]
        == "no_activity"
    )
    assert digest["title"] is None
    assert digest["body"] is None
    assert (
        digest["metadata"]["total_events"]
        == 0
    )


def test_build_daily_digest_does_not_notify_when_report_fails():
    report_service = (
        FakeActivityReportService(
            base_report(
                error=(
                    "The activity report could not "
                    "be generated."
                )
            )
        )
    )

    service = ProactiveActivityDigestService(
        activity_report_service=report_service,
    )

    digest = service.build_daily_digest(
        user_id="user-001",
    )

    assert digest["should_notify"] is False
    assert (
        digest["reason"]
        == "report_unavailable"
    )
    assert digest["title"] is None
    assert digest["body"] is None
    assert (
        digest["report"]["error"]
        == (
            "The activity report could not "
            "be generated."
        )
    )


def test_digest_uses_custom_highlight_limit():
    report_service = (
        FakeActivityReportService(
            base_report()
        )
    )

    service = ProactiveActivityDigestService(
        activity_report_service=report_service,
        highlight_limit=2,
    )

    service.build_daily_digest(
        user_id="user-001",
    )

    assert (
        report_service.calls[0]
        ["highlight_limit"]
        == 2
    )


def test_digest_is_user_scoped():
    report_service = (
        FakeActivityReportService(
            base_report()
        )
    )

    service = ProactiveActivityDigestService(
        activity_report_service=report_service,
    )

    digest = service.build_daily_digest(
        user_id="another-user",
    )

    assert (
        digest["user_id"]
        == "another-user"
    )

    assert (
        report_service.calls[0]["user_id"]
        == "another-user"
    )


def test_digest_rejects_invalid_highlight_limit():
    with pytest.raises(
        ValueError,
        match="highlight_limit must be at least 1",
    ):
        ProactiveActivityDigestService(
            highlight_limit=0,
        )