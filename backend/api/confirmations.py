from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)

from api.dependencies import CurrentUserId
from api.schemas.confirmation import (
    ConfirmationExecutionResponse,
    ConfirmationResponse,
)
from services.confirmation_execution_service import (
    ConfirmationExecutionService,
)
from services.confirmation_service import (
    ConfirmationService,
)


router = APIRouter(
    prefix="/confirmations",
    tags=["confirmations"],
)


def get_confirmation_service() -> ConfirmationService:
    return ConfirmationService()


def get_confirmation_execution_service() -> (
    ConfirmationExecutionService
):
    return ConfirmationExecutionService()


def _confirmation_response(
    confirmation: dict,
) -> ConfirmationResponse:
    return ConfirmationResponse.model_validate(
        confirmation
    )


@router.get(
    "",
    response_model=list[ConfirmationResponse],
)
def get_pending_confirmations(
    current_user_id: CurrentUserId,
    confirmation_service: Annotated[
        ConfirmationService,
        Depends(get_confirmation_service),
    ],
    conversation_id: int | None = Query(
        default=None,
        ge=1,
    ),
) -> list[ConfirmationResponse]:
    confirmations = (
        confirmation_service.list_pending_confirmations(
            user_id=current_user_id,
            conversation_id=conversation_id,
        )
    )

    return [
        _confirmation_response(
            confirmation
        )
        for confirmation in confirmations
    ]


@router.post(
    "/{confirmation_id}/approve",
    response_model=ConfirmationResponse,
)
def approve_confirmation(
    confirmation_id: int,
    current_user_id: CurrentUserId,
    confirmation_service: Annotated[
        ConfirmationService,
        Depends(get_confirmation_service),
    ],
) -> ConfirmationResponse:
    existing = (
        confirmation_service.get_confirmation(
            user_id=current_user_id,
            confirmation_id=confirmation_id,
        )
    )

    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Confirmation not found.",
        )

    if existing["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Confirmation cannot be approved "
                "in its current state."
            ),
        )

    approved = (
        confirmation_service.approve_confirmation(
            user_id=current_user_id,
            confirmation_id=confirmation_id,
        )
    )

    if approved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Confirmation not found.",
        )

    if approved["status"] != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Confirmation could not be approved "
                "in its current state."
            ),
        )

    return _confirmation_response(
        approved
    )


@router.post(
    "/{confirmation_id}/approve-and-execute",
    response_model=ConfirmationExecutionResponse,
)
def approve_and_execute_confirmation(
    confirmation_id: int,
    current_user_id: CurrentUserId,
    confirmation_service: Annotated[
        ConfirmationService,
        Depends(get_confirmation_service),
    ],
    confirmation_execution_service: Annotated[
        ConfirmationExecutionService,
        Depends(get_confirmation_execution_service),
    ],
) -> ConfirmationExecutionResponse:
    existing = (
        confirmation_service.get_confirmation(
            user_id=current_user_id,
            confirmation_id=confirmation_id,
        )
    )

    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Confirmation not found.",
        )

    if existing["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Confirmation cannot be approved "
                "in its current state."
            ),
        )

    execution = (
        confirmation_execution_service
        .approve_and_execute_confirmation(
            user_id=current_user_id,
            confirmation_id=confirmation_id,
        )
    )

    if execution.status == "unavailable":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                execution.error
                or (
                    "Confirmation is no longer "
                    "available for execution."
                )
            ),
        )

    if execution.confirmation is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                execution.error
                or (
                    "Confirmation execution could "
                    "not be completed."
                )
            ),
        )

    return ConfirmationExecutionResponse(
        confirmation=_confirmation_response(
            execution.confirmation
        ),
        success=execution.success,
        status=execution.status,
        tool_result=execution.tool_result,
        workflow_result=execution.workflow_result,
        error=execution.error,
    )


@router.post(
    "/{confirmation_id}/reject",
    response_model=ConfirmationResponse,
)
def reject_confirmation(
    confirmation_id: int,
    current_user_id: CurrentUserId,
    confirmation_service: Annotated[
        ConfirmationService,
        Depends(get_confirmation_service),
    ],
) -> ConfirmationResponse:
    existing = (
        confirmation_service.get_confirmation(
            user_id=current_user_id,
            confirmation_id=confirmation_id,
        )
    )

    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Confirmation not found.",
        )

    if existing["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Confirmation cannot be rejected "
                "in its current state."
            ),
        )

    rejected = (
        confirmation_service.reject_confirmation(
            user_id=current_user_id,
            confirmation_id=confirmation_id,
        )
    )

    if rejected is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Confirmation not found.",
        )

    if rejected["status"] != "rejected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Confirmation could not be rejected "
                "in its current state."
            ),
        )

    return _confirmation_response(
        rejected
    )


@router.get(
    "/{confirmation_id}",
    response_model=ConfirmationResponse,
)
def get_confirmation(
    confirmation_id: int,
    current_user_id: CurrentUserId,
    confirmation_service: Annotated[
        ConfirmationService,
        Depends(get_confirmation_service),
    ],
) -> ConfirmationResponse:
    confirmation = (
        confirmation_service.get_confirmation(
            user_id=current_user_id,
            confirmation_id=confirmation_id,
        )
    )

    if confirmation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Confirmation not found.",
        )

    return _confirmation_response(
        confirmation
    )