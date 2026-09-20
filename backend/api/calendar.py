from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import CurrentUserId
from api.schemas.calendar import (
    CalendarAuthorizationUrlResponse,
    CalendarConnectionResponse,
    CalendarConnectionStatusResponse,
)
from services.google_calendar_oauth_service import (
    GoogleCalendarOAuthService,
)


router = APIRouter(
    prefix="/integrations/google/calendar",
    tags=["google-calendar"],
)


def get_google_calendar_oauth_service() -> (
    GoogleCalendarOAuthService
):
    return GoogleCalendarOAuthService()


def _connection_response(
    connection: dict,
) -> CalendarConnectionResponse:
    return CalendarConnectionResponse(
        **connection
    )


@router.get(
    "/connect",
    response_model=CalendarAuthorizationUrlResponse,
)
def connect_google_calendar(
    current_user_id: CurrentUserId,
    service: Annotated[
        GoogleCalendarOAuthService,
        Depends(
            get_google_calendar_oauth_service
        ),
    ],
) -> CalendarAuthorizationUrlResponse:
    try:
        authorization_url = (
            service.build_authorization_url(
                user_id=current_user_id,
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return CalendarAuthorizationUrlResponse(
        authorization_url=authorization_url
    )


@router.get(
    "/callback",
    response_model=CalendarConnectionResponse,
)
def google_calendar_callback(
    state: str,
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    service: Annotated[
        GoogleCalendarOAuthService,
        Depends(
            get_google_calendar_oauth_service
        ),
    ] = None,
) -> CalendarConnectionResponse:
    if error is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Google Calendar authorization was "
                "not completed."
            ),
        )

    if code is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Google Calendar authorization code "
                "is required."
            ),
        )

    try:
        connection = service.complete_authorization(
            state=state,
            code=code,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return _connection_response(
        connection
    )


@router.get(
    "/status",
    response_model=CalendarConnectionStatusResponse,
)
def google_calendar_status(
    current_user_id: CurrentUserId,
    service: Annotated[
        GoogleCalendarOAuthService,
        Depends(
            get_google_calendar_oauth_service
        ),
    ],
) -> CalendarConnectionStatusResponse:
    try:
        connection = service.get_connection(
            user_id=current_user_id,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return CalendarConnectionStatusResponse(
        connected=connection is not None,
        connection=(
            None
            if connection is None
            else _connection_response(
                connection
            )
        ),
    )


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
)
def disconnect_google_calendar(
    current_user_id: CurrentUserId,
    service: Annotated[
        GoogleCalendarOAuthService,
        Depends(
            get_google_calendar_oauth_service
        ),
    ],
) -> None:
    try:
        deleted = service.disconnect(
            user_id=current_user_id,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Google Calendar is not connected.",
        )
