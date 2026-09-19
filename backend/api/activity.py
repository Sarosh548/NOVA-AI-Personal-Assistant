from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from api.dependencies import CurrentUserId
from api.schemas.activity import ActivityEventResponse
from services.activity_event_service import (
    ActivityEventService,
)


router = APIRouter(
    prefix="/activity",
    tags=["activity"],
)


def get_activity_event_service() -> ActivityEventService:
    return ActivityEventService()


@router.get(
    "",
    response_model=list[ActivityEventResponse],
)
def get_activity(
    current_user_id: CurrentUserId,
    activity_event_service: Annotated[
        ActivityEventService,
        Depends(get_activity_event_service),
    ],
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),
    event_type: str | None = Query(
        default=None,
        max_length=50,
    ),
    source: str | None = Query(
        default=None,
        max_length=50,
    ),
    since: datetime | None = None,
) -> list[ActivityEventResponse]:
    events = (
        activity_event_service.list_events(
            user_id=current_user_id,
            limit=limit,
            event_type=event_type,
            source=source,
            since=since,
        )
    )

    return [
        ActivityEventResponse(
            id=event["id"],
            conversation_id=event[
                "conversation_id"
            ],
            workflow_id=event[
                "workflow_id"
            ],
            event_type=event[
                "event_type"
            ],
            source=event["source"],
            status=event["status"],
            title=event["title"],
            summary=event["summary"],
            metadata=event["metadata"],
            created_at=event[
                "created_at"
            ],
        )
        for event in events
    ]