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
from api.schemas.workflow import (
    WorkflowActionResponse,
    WorkflowResponse,
)
from services.workflow_service import WorkflowService


router = APIRouter(
    prefix="/workflows",
    tags=["workflows"],
)


def get_workflow_service() -> WorkflowService:
    return WorkflowService()


def _workflow_response(
    workflow: dict,
) -> WorkflowResponse:
    return WorkflowResponse.model_validate(
        workflow
    )


@router.get(
    "",
    response_model=list[WorkflowResponse],
)
def get_workflows(
    current_user_id: CurrentUserId,
    workflow_service: Annotated[
        WorkflowService,
        Depends(get_workflow_service),
    ],
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),
) -> list[WorkflowResponse]:
    workflows = workflow_service.list_workflows(
        user_id=current_user_id,
        limit=limit,
    )

    return [
        _workflow_response(
            workflow
        )
        for workflow in workflows
    ]


@router.post(
    "/{workflow_id}/cancel",
    response_model=WorkflowActionResponse,
)
def cancel_workflow(
    workflow_id: int,
    current_user_id: CurrentUserId,
    workflow_service: Annotated[
        WorkflowService,
        Depends(get_workflow_service),
    ],
) -> WorkflowActionResponse:
    existing = workflow_service.get_workflow(
        user_id=current_user_id,
        workflow_id=workflow_id,
    )

    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found.",
        )

    if existing["status"] in {
        "completed",
        "cancelled",
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Workflow cannot be cancelled "
                "in its current state."
            ),
        )

    cancelled = workflow_service.cancel_workflow(
        user_id=current_user_id,
        workflow_id=workflow_id,
    )

    if cancelled is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Workflow could not be cancelled "
                "in its current state."
            ),
        )

    return WorkflowActionResponse(
        action="cancel",
        updated=True,
    )


@router.get(
    "/{workflow_id}",
    response_model=WorkflowResponse,
)
def get_workflow(
    workflow_id: int,
    current_user_id: CurrentUserId,
    workflow_service: Annotated[
        WorkflowService,
        Depends(get_workflow_service),
    ],
) -> WorkflowResponse:
    workflow = workflow_service.get_workflow(
        user_id=current_user_id,
        workflow_id=workflow_id,
    )

    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found.",
        )

    return _workflow_response(
        workflow
    )