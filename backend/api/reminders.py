from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Response,
    status,
)

from api.dependencies import CurrentUserId
from api.schemas.reminder import (
    ReminderActionResponse,
    ReminderCreateRequest,
    ReminderCreatedResponse,
    ReminderResponse,
    ReminderUpdateRequest,
    ReminderUpdateResponse,
)
from services.idempotency_service import IdempotencyService
from services.reminder_service import ReminderService


idempotency_service = IdempotencyService()


router = APIRouter(
    prefix="/reminders",
    tags=["reminders"],
)


def get_reminder_service() -> ReminderService:
    return ReminderService()


@router.post(
    "",
    response_model=ReminderCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_reminder(
    request: ReminderCreateRequest,
    current_user_id: CurrentUserId,
    reminder_service: Annotated[
        ReminderService,
        Depends(get_reminder_service),
    ],
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
) -> ReminderCreatedResponse:
    claim = None

    if idempotency_key is not None:
        request_hash = (
            IdempotencyService.build_request_hash(
                {
                    "title": request.title,
                    "reminder_time": request.reminder_time,
                }
            )
        )

        claim = idempotency_service.claim_or_replay(
            user_id=current_user_id,
            endpoint="/reminders",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

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
                headers={"Retry-After": "1"},
            )

        if claim["status"] == "replay":
            return ReminderCreatedResponse.model_validate(
                claim["response_body"]
            )

    try:
        reminder_id = (
            reminder_service.create_reminder(
                user_id=current_user_id,
                title=request.title,
                reminder_time=request.reminder_time,
            )
        )

    except ValueError as exc:
        if claim is not None and claim.get("claim_token"):
            try:
                idempotency_service.fail(
                    record_id=claim["record_id"],
                    claim_token=claim["claim_token"],
                    error="Reminder creation failed.",
                )
            except Exception:
                pass

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except Exception:
        if claim is not None and claim.get("claim_token"):
            try:
                idempotency_service.fail(
                    record_id=claim["record_id"],
                    claim_token=claim["claim_token"],
                    error="Reminder creation failed.",
                )
            except Exception:
                pass

        raise

    response_payload = {
        "id": reminder_id,
    }

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

    return ReminderCreatedResponse(
        id=reminder_id,
    )


@router.get(
    "",
    response_model=list[ReminderResponse],
)
def get_reminders(
    current_user_id: CurrentUserId,
    reminder_service: Annotated[
        ReminderService,
        Depends(get_reminder_service),
    ],
) -> list[ReminderResponse]:
    reminders = (
        reminder_service.get_pending_reminders(
            user_id=current_user_id,
        )
    )

    return [
        ReminderResponse.model_validate(
            reminder
        )
        for reminder in reminders
    ]


@router.patch(
    "/{reminder_id}",
    response_model=ReminderUpdateResponse,
)
def update_reminder(
    reminder_id: int,
    request: ReminderUpdateRequest,
    current_user_id: CurrentUserId,
    reminder_service: Annotated[
        ReminderService,
        Depends(get_reminder_service),
    ],
) -> ReminderUpdateResponse:
    try:
        updated = reminder_service.update_reminder(
            reminder_id=reminder_id,
            user_id=current_user_id,
            title=request.title,
            reminder_time=request.reminder_time,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reminder not found.",
        )

    return ReminderUpdateResponse(
        updated=True,
    )


@router.post(
    "/{reminder_id}/complete",
    response_model=ReminderActionResponse,
)
def complete_reminder(
    reminder_id: int,
    current_user_id: CurrentUserId,
    reminder_service: Annotated[
        ReminderService,
        Depends(get_reminder_service),
    ],
) -> ReminderActionResponse:
    updated = reminder_service.complete_reminder(
        reminder_id=reminder_id,
        user_id=current_user_id,
    )

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reminder not found.",
        )

    return ReminderActionResponse(
        action="complete",
        updated=True,
    )


@router.post(
    "/{reminder_id}/cancel",
    response_model=ReminderActionResponse,
)
def cancel_reminder(
    reminder_id: int,
    current_user_id: CurrentUserId,
    reminder_service: Annotated[
        ReminderService,
        Depends(get_reminder_service),
    ],
) -> ReminderActionResponse:
    updated = reminder_service.cancel_reminder(
        reminder_id=reminder_id,
        user_id=current_user_id,
    )

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reminder not found.",
        )

    return ReminderActionResponse(
        action="cancel",
        updated=True,
    )


@router.delete(
    "/{reminder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_reminder(
    reminder_id: int,
    current_user_id: CurrentUserId,
    reminder_service: Annotated[
        ReminderService,
        Depends(get_reminder_service),
    ],
) -> Response:
    deleted = reminder_service.delete_reminder(
        reminder_id=reminder_id,
        user_id=current_user_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reminder not found.",
        )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )