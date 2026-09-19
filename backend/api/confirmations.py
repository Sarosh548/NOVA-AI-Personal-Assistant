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
    ConfirmationResponse,
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
        ConfirmationResponse.model_validate(
            confirmation
        )
        for confirmation in confirmations
    ]


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

    return ConfirmationResponse.model_validate(
        confirmation
    )