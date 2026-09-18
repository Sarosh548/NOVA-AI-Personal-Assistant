from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.activity_event import ActivityEvent
from services.activity_event_service import (
    ActivityEventService,
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

    service = ActivityEventService(
        db_engine=db_engine
    )

    return (
        db_engine,
        service,
    )


def teardown_runtime(
    db_engine,
):
    ActivityEvent.__table__.drop(
        bind=db_engine
    )

    db_engine.dispose()


def test_record_event_persists_structured_activity():
    db_engine, service = build_runtime()

    try:
        created_at = datetime(
            2026,
            9,
            18,
            6,
            0,
            0,
            tzinfo=timezone.utc,
        )

        event = service.record_event(
            user_id="user-001",
            event_type="workflow_completed",
            source="workflow",
            title="Workflow completed",
            summary="Autonomous workflow completed successfully.",
            status="success",
            conversation_id=10,
            workflow_id=25,
            metadata={
                "step_count": 2,
                "duration_seconds": 4,
            },
            created_at=created_at,
        )

        assert event["id"] is not None
        assert event["user_id"] == "user-001"
        assert event["conversation_id"] == 10
        assert event["workflow_id"] == 25
        assert event["event_type"] == "workflow_completed"
        assert event["source"] == "workflow"
        assert event["status"] == "success"
        assert event["title"] == "Workflow completed"
        assert (
            event["summary"]
            == "Autonomous workflow completed successfully."
        )
        assert event["metadata"] == {
            "step_count": 2,
            "duration_seconds": 4,
        }

        assert event["created_at"] == datetime(
            2026,
            9,
            18,
            6,
            0,
            0,
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_timezone_aware_created_at_is_normalized_to_utc():
    db_engine, service = build_runtime()

    try:
        created_at = datetime(
            2026,
            9,
            18,
            11,
            0,
            0,
            tzinfo=timezone(
                timedelta(hours=5)
            ),
        )

        event = service.record_event(
            user_id="user-001",
            event_type="test",
            source="test",
            title="Timezone test",
            summary="Timezone normalization.",
            created_at=created_at,
        )

        assert event["created_at"] == datetime(
            2026,
            9,
            18,
            6,
            0,
            0,
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_list_events_returns_newest_first():
    db_engine, service = build_runtime()

    try:
        first_time = datetime(
            2026,
            9,
            18,
            6,
            0,
            0,
        )

        second_time = datetime(
            2026,
            9,
            18,
            6,
            5,
            0,
        )

        service.record_event(
            user_id="user-001",
            event_type="workflow_created",
            source="workflow",
            title="Workflow created",
            summary="Workflow was scheduled.",
            created_at=first_time,
        )

        service.record_event(
            user_id="user-001",
            event_type="workflow_completed",
            source="workflow",
            title="Workflow completed",
            summary="Workflow completed.",
            status="success",
            created_at=second_time,
        )

        events = service.list_events(
            user_id="user-001"
        )

        assert len(events) == 2

        assert (
            events[0]["event_type"]
            == "workflow_completed"
        )

        assert (
            events[1]["event_type"]
            == "workflow_created"
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_list_events_filters_by_event_type_and_source():
    db_engine, service = build_runtime()

    try:
        created_at = datetime(
            2026,
            9,
            18,
            6,
            0,
            0,
        )

        service.record_event(
            user_id="user-001",
            event_type="workflow_completed",
            source="workflow",
            title="Workflow completed",
            summary="Done.",
            status="success",
            created_at=created_at,
        )

        service.record_event(
            user_id="user-001",
            event_type="message_received",
            source="whatsapp",
            title="Message received",
            summary="New message.",
            created_at=created_at,
        )

        workflow_events = service.list_events(
            user_id="user-001",
            event_type="workflow_completed",
            source="workflow",
        )

        assert len(workflow_events) == 1
        assert (
            workflow_events[0]["event_type"]
            == "workflow_completed"
        )
        assert (
            workflow_events[0]["source"]
            == "workflow"
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_list_events_filters_by_since():
    db_engine, service = build_runtime()

    try:
        older = datetime(
            2026,
            9,
            18,
            5,
            0,
            0,
        )

        newer = datetime(
            2026,
            9,
            18,
            7,
            0,
            0,
        )

        service.record_event(
            user_id="user-001",
            event_type="older",
            source="test",
            title="Older event",
            summary="Older.",
            created_at=older,
        )

        service.record_event(
            user_id="user-001",
            event_type="newer",
            source="test",
            title="Newer event",
            summary="Newer.",
            created_at=newer,
        )

        events = service.list_events(
            user_id="user-001",
            since=datetime(
                2026,
                9,
                18,
                6,
                0,
                0,
            ),
        )

        assert len(events) == 1
        assert (
            events[0]["event_type"]
            == "newer"
        )

    finally:
        teardown_runtime(
            db_engine
        )


def test_empty_required_text_is_rejected():
    db_engine, service = build_runtime()

    try:
        with pytest.raises(
            ValueError,
            match="user_id",
        ):
            service.record_event(
                user_id="   ",
                event_type="test",
                source="test",
                title="Title",
                summary="Summary",
            )

        with pytest.raises(
            ValueError,
            match="event_type",
        ):
            service.record_event(
                user_id="user-001",
                event_type=" ",
                source="test",
                title="Title",
                summary="Summary",
            )

        with pytest.raises(
            ValueError,
            match="source",
        ):
            service.record_event(
                user_id="user-001",
                event_type="test",
                source=" ",
                title="Title",
                summary="Summary",
            )

        with pytest.raises(
            ValueError,
            match="title",
        ):
            service.record_event(
                user_id="user-001",
                event_type="test",
                source="test",
                title=" ",
                summary="Summary",
            )

        with pytest.raises(
            ValueError,
            match="summary",
        ):
            service.record_event(
                user_id="user-001",
                event_type="test",
                source="test",
                title="Title",
                summary=" ",
            )

    finally:
        teardown_runtime(
            db_engine
        )


def test_invalid_status_is_rejected():
    db_engine, service = build_runtime()

    try:
        with pytest.raises(
            ValueError,
            match="status",
        ):
            service.record_event(
                user_id="user-001",
                event_type="test",
                source="test",
                title="Invalid status",
                summary="This should fail.",
                status="unknown",
            )

    finally:
        teardown_runtime(
            db_engine
        )


def test_events_are_scoped_to_user():
    db_engine, service = build_runtime()

    try:
        created_at = datetime(
            2026,
            9,
            18,
            6,
            0,
            0,
        )

        service.record_event(
            user_id="user-001",
            event_type="test",
            source="test",
            title="User one",
            summary="Private event.",
            created_at=created_at,
        )

        service.record_event(
            user_id="user-002",
            event_type="test",
            source="test",
            title="User two",
            summary="Private event.",
            created_at=created_at,
        )

        events = service.list_events(
            user_id="user-001"
        )

        assert len(events) == 1
        assert events[0]["user_id"] == "user-001"
        assert events[0]["title"] == "User one"

    finally:
        teardown_runtime(
            db_engine
        )