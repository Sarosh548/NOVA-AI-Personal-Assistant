from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Response,
    status,
)

from api.dependencies import CurrentUserId
from api.schemas.memory import (
    MemoryCategory,
    MemoryImportance,
    MemoryResponse,
    MemorySearchResponse,
    MemoryUpdateRequest,
)
from services.memory_service import MemoryService


router = APIRouter(
    prefix="/memories",
    tags=["memories"],
)


def get_memory_service() -> MemoryService:
    return MemoryService()


def _memory_response(
    memory: dict,
) -> MemoryResponse:
    return MemoryResponse.model_validate(
        memory
    )


def _memory_search_response(
    memory: dict,
) -> MemorySearchResponse:
    return MemorySearchResponse.model_validate(
        memory
    )


@router.get(
    "",
    response_model=list[MemoryResponse],
)
def list_memories(
    current_user_id: CurrentUserId,
    memory_service: Annotated[
        MemoryService,
        Depends(get_memory_service),
    ],
    category: MemoryCategory | None = Query(
        default=None,
    ),
    importance: MemoryImportance | None = Query(
        default=None,
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=100,
    ),
) -> list[MemoryResponse]:
    try:
        memories = memory_service.list_memories(
            user_id=current_user_id,
            category=category,
            importance=importance,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return [
        _memory_response(
            memory
        )
        for memory in memories
    ]


@router.get(
    "/search",
    response_model=list[MemorySearchResponse],
)
def search_memories(
    current_user_id: CurrentUserId,
    memory_service: Annotated[
        MemoryService,
        Depends(get_memory_service),
    ],
    query: str = Query(
        min_length=1,
        max_length=10000,
    ),
    threshold: float = Query(
        default=0.65,
        ge=0.0,
        le=1.0,
    ),
    limit: int = Query(
        default=8,
        ge=1,
        le=50,
    ),
) -> list[MemorySearchResponse]:
    try:
        memories = memory_service.find_similar_memories(
            user_id=current_user_id,
            new_memory=query,
            threshold=threshold,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return [
        _memory_search_response(
            memory
        )
        for memory in memories
    ]


@router.get(
    "/{memory_id}",
    response_model=MemoryResponse,
)
def get_memory(
    memory_id: int = Path(
        ge=1,
    ),
    current_user_id: CurrentUserId = None,
    memory_service: Annotated[
        MemoryService,
        Depends(get_memory_service),
    ] = None,
) -> MemoryResponse:
    memory = memory_service.get_memory(
        user_id=current_user_id,
        memory_id=memory_id,
    )

    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found.",
        )

    return _memory_response(
        memory
    )


@router.patch(
    "/{memory_id}",
    response_model=MemoryResponse,
)
def update_memory(
    memory_id: int = Path(
        ge=1,
    ),
    request: MemoryUpdateRequest = None,
    current_user_id: CurrentUserId = None,
    memory_service: Annotated[
        MemoryService,
        Depends(get_memory_service),
    ] = None,
) -> MemoryResponse:
    try:
        updated = memory_service.update_memory(
            user_id=current_user_id,
            memory_id=memory_id,
            memory_text=request.memory,
            category=request.category,
            importance=request.importance,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found.",
        )

    memory = memory_service.get_memory(
        user_id=current_user_id,
        memory_id=memory_id,
    )

    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found.",
        )

    return _memory_response(
        memory
    )


@router.delete(
    "/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_memory(
    memory_id: int = Path(
        ge=1,
    ),
    current_user_id: CurrentUserId = None,
    memory_service: Annotated[
        MemoryService,
        Depends(get_memory_service),
    ] = None,
) -> Response:
    try:
        deleted = memory_service.delete_memory(
            user_id=current_user_id,
            memory_id=memory_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found.",
        )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )
