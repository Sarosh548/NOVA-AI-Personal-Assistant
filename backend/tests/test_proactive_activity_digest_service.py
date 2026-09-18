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
        timezone_name,
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "now": now,
                "highlight_limit": (
                    highlight_limit
                ),
                "timezone_name": timezone_name,
            }
        )

        return {
            **self.report,
            "timezone": timezone_name,
        }


class FakePreferences:
    def __init__(
        self,
        *,
        timezone="Asia/Karachi",
        enabled=True,
        delivery_hour=21,
        delivery_minute=0,
    ):
        self.timezone = timezone
        self.daily_activity_digest_enabled = (
            enabled
        )
        self.delivery_hour = delivery_hour
        self.delivery_minute = delivery_minute


class FakePreferencesService:
    def __init__(
        self,
        preferences=None,
    ):
        self.preferences = (
            preferences
            if preferences is not None
            else FakePreferences()
        )
        self.calls = []

    def get_or_create(
        self,
        *,
        user_id,
    ):
        self.calls.append(
            user_id
        )

        return self.preferences


def build_report(
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


def build_service(
    *,
    report=None,
    preferences=None,
    highlight_limit=5,
):
    report_service = (
        FakeActivityReportService(
            report
            if report is not None
            else build_report()
        )
    )

    preferences_service = (
        FakePreferencesService(
            preferences
        )
    )

    service = ProactiveActivityDigestService(
        activity_report_service=report_service,
        highlight_limit=highlight_limit,
        user_notification_preferences_service=(
            preferences_service
        ),
    )

    return (
        service,
        report_service,
        preferences_service,
    )


def test_build_daily_digest_creates_notification_payload():
    (
        service,
        report_service,
        preferences_service,
    ) = build_service()

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

    assert preferences_service.calls == [
        "user-001"
    ]

    assert report_service.calls == [
        {
            "user_id": "user-001",
            "now": now,
            "highlight_limit": 5,
            "timezone_name": "Asia/Karachi",
        }
    ]


def test_digest_uses_user_timezone():
    preferences = FakePreferences(
        timezone="America/New_York"
    )

    (
        service,
        report_service,
        _,
    ) = build_service(
        preferences=preferences
    )

    service.build_daily_digest(
        user_id="user-ny",
        now=datetime(
            2026,
            9,
            18,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )

    assert (
        report_service.calls[0]
        ["timezone_name"]
        == "America/New_York"
    )


def test_build_daily_digest_does_not_notify_when_disabled():
    preferences = FakePreferences(
        enabled=False
    )

    (
        service,
        report_service,
        _,
    ) = build_service(
        preferences=preferences
    )

    digest = service.build_daily_digest(
        user_id="user-disabled",
    )

    assert digest["should_notify"] is False
    assert (
        digest["reason"]
        == "digest_disabled"
    )
    assert digest["title"] is None
    assert digest["body"] is None
    assert (
        digest["metadata"]["timezone"]
        == "Asia/Karachi"
    )

    assert report_service.calls == []


def test_build_daily_digest_does_not_notify_when_no_activity():
    (
        service,
        _,
        _,
    ) = build_service(
        report=build_report(
            total_events=0
        )
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
    (
        service,
        _,
        _,
    ) = build_service(
        report=build_report(
            error=(
                "The activity report could not "
                "be generated."
            )
        )
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
    (
        service,
        report_service,
        _,
    ) = build_service(
        highlight_limit=2
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
    (
        service,
        report_service,
        _,
    ) = build_service()

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