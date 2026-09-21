from __future__ import annotations

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
from api.schemas.task import (
    TaskActionResponse,
    TaskCreateRequest,
    TaskCreatedResponse,
    TaskResponse,
    TaskUpdateRequest,
    TaskUpdateResponse,
)
from services.idempotency_service import IdempotencyService
from services.task_service import TaskService


idempotency_service = IdempotencyService()


router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
)


def get_task_service() -> TaskService:
    return TaskService()


@router.post(
    "",
    response_model=TaskCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    request: TaskCreateRequest,
    current_user_id: CurrentUserId,
    task_service: Annotated[
        TaskService,
        Depends(get_task_service),
    ],
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
) -> TaskCreatedResponse:
    claim = None

    if idempotency_key is not None:
        request_hash = (
            IdempotencyService.build_request_hash(
                {
                    "title": request.title,
                    "description": request.description,
                    "priority": request.priority,
                    "due_at": request.due_at,
                }
            )
        )

        claim = idempotency_service.claim_or_replay(
            user_id=current_user_id,
            endpoint="/tasks",
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
            return TaskCreatedResponse.model_validate(
                claim["response_body"]
            )

    try:
        task_id = task_service.create_task(
            user_id=current_user_id,
            title=request.title,
            description=request.description,
            priority=request.priority,
            due_at=request.due_at,
        )

    except Exception:
        if claim is not None and claim.get("claim_token"):
            try:
                idempotency_service.fail(
                    record_id=claim["record_id"],
                    claim_token=claim["claim_token"],
                    error="Task creation failed.",
                )
            except Exception:
                pass

        raise

    response_payload = {
        "id": task_id,
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

    return TaskCreatedResponse(
        id=task_id,
    )


@router.get(
    "",
    response_model=list[TaskResponse],
)
def get_tasks(
    current_user_id: CurrentUserId,
    task_service: Annotated[
        TaskService,
        Depends(get_task_service),
    ],
    task_status: str | None = Query(
        default=None,
        alias="status",
    ),
) -> list[TaskResponse]:
    try:
        tasks = task_service.get_tasks(
            user_id=current_user_id,
            status=task_status,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return [
        TaskResponse.model_validate(
            task
        )
        for task in tasks
    ]


@router.patch(
    "/{task_id}",
    response_model=TaskUpdateResponse,
)
def update_task(
    task_id: int,
    request: TaskUpdateRequest,
    current_user_id: CurrentUserId,
    task_service: Annotated[
        TaskService,
        Depends(get_task_service),
    ],
) -> TaskUpdateResponse:
    try:
        updated = task_service.update_task(
            task_id=task_id,
            user_id=current_user_id,
            priority=request.priority,
            due_at=request.due_at,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        )

    return TaskUpdateResponse(
        updated=True,
    )


@router.post(
    "/{task_id}/start",
    response_model=TaskActionResponse,
)
def start_task(
    task_id: int,
    current_user_id: CurrentUserId,
    task_service: Annotated[
        TaskService,
        Depends(get_task_service),
    ],
) -> TaskActionResponse:
    updated = task_service.start_task(
        task_id=task_id,
        user_id=current_user_id,
    )

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        )

    return TaskActionResponse(
        action="start",
        updated=True,
    )


@router.post(
    "/{task_id}/complete",
    response_model=TaskActionResponse,
)
def complete_task(
    task_id: int,
    current_user_id: CurrentUserId,
    task_service: Annotated[
        TaskService,
        Depends(get_task_service),
    ],
) -> TaskActionResponse:
    updated = task_service.complete_task(
        task_id=task_id,
        user_id=current_user_id,
    )

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        )

    return TaskActionResponse(
        action="complete",
        updated=True,
    )


@router.post(
    "/{task_id}/cancel",
    response_model=TaskActionResponse,
)
def cancel_task(
    task_id: int,
    current_user_id: CurrentUserId,
    task_service: Annotated[
        TaskService,
        Depends(get_task_service),
    ],
) -> TaskActionResponse:
    updated = task_service.cancel_task(
        task_id=task_id,
        user_id=current_user_id,
    )

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        )

    return TaskActionResponse(
        action="cancel",
        updated=True,
    )


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_task(
    task_id: int,
    current_user_id: CurrentUserId,
    task_service: Annotated[
        TaskService,
        Depends(get_task_service),
    ],
) -> Response:
    deleted = task_service.delete_task(
        task_id=task_id,
        user_id=current_user_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )