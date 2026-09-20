from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from api.schemas.calendar import (
    CalendarEventBoundaryRequest,
    CalendarEventCreateRequest,
    CalendarEventUpdateRequest,
)


def test_boundary_accepts_date():
    value = CalendarEventBoundaryRequest(
        date=date(2026, 9, 21)
    )

    assert value.date == date(2026, 9, 21)
    assert value.dateTime is None


def test_boundary_accepts_timezone_aware_datetime():
    value = CalendarEventBoundaryRequest(
        dateTime=datetime(
            2026,
            9,
            21,
            15,
            0,
            tzinfo=timezone.utc,
        )
    )

    assert value.dateTime.tzinfo is not None


def test_boundary_rejects_both_date_and_datetime():
    with pytest.raises(
        ValidationError,
        match="Exactly one",
    ):
        CalendarEventBoundaryRequest(
            date=date(2026, 9, 21),
            dateTime=datetime(
                2026,
                9,
                21,
                15,
                0,
                tzinfo=timezone.utc,
            ),
        )


def test_create_request_rejects_mixed_boundary_types():
    with pytest.raises(
        ValidationError,
        match="same date or dateTime",
    ):
        CalendarEventCreateRequest(
            start={
                "date": "2026-09-21",
            },
            end={
                "dateTime": (
                    "2026-09-21T16:00:00+00:00"
                ),
            },
        )


def test_update_request_requires_paired_time_fields():
    with pytest.raises(
        ValidationError,
        match="provided together",
    ):
        CalendarEventUpdateRequest(
            start={
                "dateTime": (
                    "2026-09-21T15:00:00+00:00"
                ),
            }
        )
