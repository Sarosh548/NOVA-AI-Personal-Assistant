from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    status,
)
from pydantic import BaseModel, Field

from api.dependencies import CurrentUserId
from services.notification_destination_service import (
    NotificationDestinationService,
)


router = APIRouter(
    prefix="/notification-destinations",
    tags=["notification-destinations"],
)


def get_notification_destination_service() -> (
    NotificationDestinationService
):
    return NotificationDestinationService()


class NotificationDestinationCreateRequest(
    BaseModel
):
    channel: str = Field(
        default="email",
        min_length=1,
        max_length=50,
    )

    destination: str = Field(
        min_length=1,
        max_length=500,
    )

    label: str | None = Field(
        default=None,
        max_length=100,
    )

    is_default: bool = False


class NotificationDestinationResponse(
    BaseModel
):
    id: int
    user_id: str
    channel: str
    destination: str
    label: str | None
    is_enabled: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime


def _response(
    destination: dict,
) -> NotificationDestinationResponse:
    return NotificationDestinationResponse(
        **destination
    )


@router.get(
    "",
    response_model=list[
        NotificationDestinationResponse
    ],
)
def list_notification_destinations(
    current_user_id: CurrentUserId,
    service: Annotated[
        NotificationDestinationService,
        Depends(
            get_notification_destination_service
        ),
    ],
) -> list[
    NotificationDestinationResponse
]:
    try:
        destinations = (
            service.list_destinations(
                user_id=current_user_id,
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return [
        _response(
            destination
        )
        for destination in destinations
    ]


@router.post(
    "",
    response_model=NotificationDestinationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_notification_destination(
    request: NotificationDestinationCreateRequest,
    current_user_id: CurrentUserId,
    service: Annotated[
        NotificationDestinationService,
        Depends(
            get_notification_destination_service
        ),
    ],
) -> NotificationDestinationResponse:
    try:
        destination = (
            service.create_destination(
                user_id=current_user_id,
                channel=request.channel,
                destination=request.destination,
                label=request.label,
                is_default=request.is_default,
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return _response(
        destination
    )


@router.post(
    "/{destination_id}/default",
    response_model=NotificationDestinationResponse,
)
def set_default_notification_destination(
    destination_id: int,
    current_user_id: CurrentUserId,
    service: Annotated[
        NotificationDestinationService,
        Depends(
            get_notification_destination_service
        ),
    ],
) -> NotificationDestinationResponse:
    try:
        destination = (
            service.set_default_destination(
                user_id=current_user_id,
                destination_id=destination_id,
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if destination is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification destination not found.",
        )

    return _response(
        destination
    )


@router.delete(
    "/{destination_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_notification_destination(
    destination_id: int,
    current_user_id: CurrentUserId,
    service: Annotated[
        NotificationDestinationService,
        Depends(
            get_notification_destination_service
        ),
    ],
) -> Response:
    try:
        deleted = (
            service.delete_destination(
                user_id=current_user_id,
                destination_id=destination_id,
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification destination not found.",
        )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT
    )