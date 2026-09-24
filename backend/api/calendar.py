from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Response,
    status,
)

from api.dependencies import CurrentUserId
from api.schemas.calendar import (
    CalendarAuthorizationUrlResponse,
    CalendarConnectionResponse,
    CalendarConnectionStatusResponse,
    CalendarEventCreateRequest,
    CalendarEventDeleteResponse,
    CalendarEventListResponse,
    CalendarEventUpdateRequest,
    CalendarSendUpdates,
)
from services.google_calendar_oauth_service import (
    GoogleCalendarOAuthService,
)
from services.google_calendar_service import (
    GoogleCalendarAPIError,
    GoogleCalendarService,
)
from services.idempotency_service import IdempotencyService


idempotency_service = IdempotencyService()


router = APIRouter(
    prefix="/integrations/google/calendar",
    tags=["google-calendar"],
)


def get_google_calendar_oauth_service() -> GoogleCalendarOAuthService:
    return GoogleCalendarOAuthService()


def get_google_calendar_service() -> GoogleCalendarService:
    return GoogleCalendarService()


def _connection_response(
    connection: dict,
) -> CalendarConnectionResponse:
    return CalendarConnectionResponse(
        **connection
    )


def _event_payload(
    event,
) -> dict:
    payload = event.model_dump(
        by_alias=True,
        exclude_none=True,
    )

    for field_name in (
        "start",
        "end",
    ):
        boundary = payload.get(
            field_name
        )

        if not isinstance(
            boundary,
            dict,
        ):
            continue

        if isinstance(
            boundary.get("date"),
            date,
        ):
            boundary["date"] = boundary[
                "date"
            ].isoformat()

        if isinstance(
            boundary.get("dateTime"),
            datetime,
        ):
            boundary["dateTime"] = boundary[
                "dateTime"
            ].isoformat()

    attendees = payload.get(
        "attendees"
    )

    if isinstance(
        attendees,
        list,
    ):
        for attendee in attendees:
            if not isinstance(
                attendee,
                dict,
            ):
                continue

            for field_name in (
                "email",
                "displayName",
            ):
                value = attendee.get(
                    field_name
                )

                if isinstance(
                    value,
                    str,
                ):
                    attendee[field_name] = (
                        value.strip()
                    )

    return payload


def _raise_calendar_error(
    error: Exception,
) -> None:
    if isinstance(
        error,
        GoogleCalendarAPIError,
    ):
        code = error.status_code

        if code in {
            401,
            403,
            404,
            409,
            412,
            429,
        }:
            raise HTTPException(
                status_code=code,
                detail=str(error),
            ) from error

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error

    if isinstance(
        error,
        ValueError,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=(
            "Google Calendar request could not be completed."
        ),
    ) from error


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
    "/events",
    response_model=CalendarEventListResponse,
)
def list_calendar_events(
    current_user_id: CurrentUserId,
    calendar_service: Annotated[
        GoogleCalendarService,
        Depends(get_google_calendar_service),
    ],
    calendar_id: str | None = Query(
        default=None,
    ),
    time_min: datetime | None = Query(
        default=None,
    ),
    time_max: datetime | None = Query(
        default=None,
    ),
    query: str | None = Query(
        default=None,
        max_length=500,
    ),
    max_results: int = Query(
        default=50,
        ge=1,
        le=2500,
    ),
    page_token: str | None = Query(
        default=None,
        max_length=2000,
    ),
    single_events: bool = Query(
        default=True,
    ),
    order_by: str = Query(
        default="startTime",
        pattern="^(startTime|updated)$",
    ),
    show_deleted: bool = Query(
        default=False,
    ),
) -> CalendarEventListResponse:
    try:
        result = calendar_service.list_events(
            user_id=current_user_id,
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            query=query,
            max_results=max_results,
            page_token=page_token,
            single_events=single_events,
            order_by=order_by,
            show_deleted=show_deleted,
        )

    except (
        GoogleCalendarAPIError,
        ValueError,
        TypeError,
    ) as exc:
        _raise_calendar_error(
            exc
        )

    return CalendarEventListResponse(
        **result
    )


@router.post(
    "/events",
    status_code=status.HTTP_201_CREATED,
)
def create_calendar_event(
    request: CalendarEventCreateRequest,
    current_user_id: CurrentUserId,
    calendar_service: Annotated[
        GoogleCalendarService,
        Depends(get_google_calendar_service),
    ],
    calendar_id: str | None = Query(
        default=None,
    ),
    send_updates: CalendarSendUpdates = Query(
        default="all",
    ),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
) -> dict:
    event_payload = _event_payload(
        request
    )

    claim = None

    if idempotency_key is not None:
        request_hash = (
            IdempotencyService.build_request_hash(
                {
                    "calendar_id": calendar_id,
                    "send_updates": send_updates,
                    "event": event_payload,
                }
            )
        )

        try:
            claim = idempotency_service.claim_or_replay(
                user_id=current_user_id,
                endpoint=(
                    "/integrations/google/calendar/events"
                ),
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )

        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        if claim["status"] == "conflict":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Idempotency-Key was already used "
                    "for a different request."
                ),
            )

        if claim["status"] == "in_progress":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This request is already being processed."
                ),
                headers={
                    "Retry-After": "1",
                },
            )

        if claim["status"] == "replay":
            return claim["response_body"]

    try:
        create_kwargs = {
            "user_id": current_user_id,
            "calendar_id": calendar_id,
            "event": event_payload,
            "send_updates": send_updates,
        }

        if idempotency_key is not None:
            create_kwargs["idempotency_key"] = idempotency_key

        response_payload = calendar_service.create_event(
            **create_kwargs
        )

    except (
        GoogleCalendarAPIError,
        ValueError,
        TypeError,
    ) as exc:
        if claim is not None and claim.get("claim_token"):
            try:
                idempotency_service.fail(
                    record_id=claim["record_id"],
                    claim_token=claim["claim_token"],
                    error="Calendar event creation failed.",
                )
            except Exception:
                pass

        _raise_calendar_error(
            exc
        )

    if claim is not None and claim.get("claim_token"):
        try:
            idempotency_service.complete(
                record_id=claim["record_id"],
                claim_token=claim["claim_token"],
                response_status=status.HTTP_201_CREATED,
                response_body=response_payload,
            )
        except Exception:
            pass

    return response_payload


@router.get(
    "/events/{event_id}",
)
def get_calendar_event(
    event_id: str,
    current_user_id: CurrentUserId,
    calendar_service: Annotated[
        GoogleCalendarService,
        Depends(get_google_calendar_service),
    ],
    calendar_id: str | None = Query(
        default=None,
    ),
) -> dict:
    try:
        return calendar_service.get_event(
            user_id=current_user_id,
            event_id=event_id,
            calendar_id=calendar_id,
        )

    except (
        GoogleCalendarAPIError,
        ValueError,
        TypeError,
    ) as exc:
        _raise_calendar_error(
            exc
        )


@router.patch(
    "/events/{event_id}",
)
def update_calendar_event(
    event_id: str,
    request: CalendarEventUpdateRequest,
    current_user_id: CurrentUserId,
    calendar_service: Annotated[
        GoogleCalendarService,
        Depends(get_google_calendar_service),
    ],
    calendar_id: str | None = Query(
        default=None,
    ),
    send_updates: CalendarSendUpdates = Query(
        default="all",
    ),
    if_match: str | None = Header(
        default=None,
        alias="If-Match",
    ),
) -> dict:
    try:
        update_kwargs = {
            "user_id": current_user_id,
            "event_id": event_id,
            "calendar_id": calendar_id,
            "event": _event_payload(
                request
            ),
            "send_updates": send_updates,
        }

        if if_match is not None:
            update_kwargs["if_match"] = if_match

        return calendar_service.update_event(
            **update_kwargs
        )

    except (
        GoogleCalendarAPIError,
        ValueError,
        TypeError,
    ) as exc:
        _raise_calendar_error(
            exc
        )


@router.delete(
    "/events/{event_id}",
    response_model=CalendarEventDeleteResponse,
)
def delete_calendar_event(
    event_id: str,
    current_user_id: CurrentUserId,
    calendar_service: Annotated[
        GoogleCalendarService,
        Depends(get_google_calendar_service),
    ],
    calendar_id: str | None = Query(
        default=None,
    ),
    send_updates: CalendarSendUpdates = Query(
        default="all",
    ),
    if_match: str | None = Header(
        default=None,
        alias="If-Match",
    ),
) -> CalendarEventDeleteResponse:
    try:
        delete_kwargs = {
            "user_id": current_user_id,
            "event_id": event_id,
            "calendar_id": calendar_id,
            "send_updates": send_updates,
        }

        if if_match is not None:
            delete_kwargs["if_match"] = if_match

        result = calendar_service.delete_event(
            **delete_kwargs
        )

    except (
        GoogleCalendarAPIError,
        ValueError,
        TypeError,
    ) as exc:
        _raise_calendar_error(
            exc
        )

    return CalendarEventDeleteResponse(
        **result
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
    response_model=None,
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
) -> Response:
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

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )
