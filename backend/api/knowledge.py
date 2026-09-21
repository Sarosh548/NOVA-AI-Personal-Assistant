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
from api.schemas.knowledge import (
    KnowledgeDocumentCreateRequest,
    KnowledgeDocumentDetailResponse,
    KnowledgeDocumentResponse,
    KnowledgeSearchResponse,
    KnowledgeUrlCreateRequest,
)
from services.knowledge_service import KnowledgeService


router = APIRouter(
    prefix="/knowledge",
    tags=["knowledge"],
)


def get_knowledge_service() -> KnowledgeService:
    return KnowledgeService()


def _document_response(
    document: dict,
) -> KnowledgeDocumentResponse:
    return KnowledgeDocumentResponse.model_validate(
        document
    )


def _document_detail_response(
    document: dict,
) -> KnowledgeDocumentDetailResponse:
    return KnowledgeDocumentDetailResponse.model_validate(
        document
    )


def _search_response(
    match: dict,
) -> KnowledgeSearchResponse:
    return KnowledgeSearchResponse.model_validate(
        match
    )


@router.post(
    "/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_document(
    request: KnowledgeDocumentCreateRequest,
    current_user_id: CurrentUserId,
    service: Annotated[
        KnowledgeService,
        Depends(get_knowledge_service),
    ],
) -> KnowledgeDocumentResponse:
    try:
        document = service.create_document(
            user_id=current_user_id,
            title=request.title,
            content=request.content,
            source=request.source,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return _document_response(
        document
    )


@router.post(
    "/urls",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_document_from_url(
    request: KnowledgeUrlCreateRequest,
    current_user_id: CurrentUserId,
    service: Annotated[
        KnowledgeService,
        Depends(get_knowledge_service),
    ],
) -> KnowledgeDocumentResponse:
    try:
        document = service.create_document_from_url(
            user_id=current_user_id,
            url=request.url,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return _document_response(
        document
    )


@router.get(
    "/documents",
    response_model=list[KnowledgeDocumentResponse],
)
def list_documents(
    current_user_id: CurrentUserId,
    service: Annotated[
        KnowledgeService,
        Depends(get_knowledge_service),
    ],
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),
) -> list[KnowledgeDocumentResponse]:
    try:
        documents = service.list_documents(
            user_id=current_user_id,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return [
        _document_response(document)
        for document in documents
    ]


@router.get(
    "/search",
    response_model=list[KnowledgeSearchResponse],
)
def search_knowledge(
    current_user_id: CurrentUserId,
    service: Annotated[
        KnowledgeService,
        Depends(get_knowledge_service),
    ],
    query: str = Query(
        min_length=1,
        max_length=250_000,
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
) -> list[KnowledgeSearchResponse]:
    try:
        matches = service.search(
            user_id=current_user_id,
            query=query,
            threshold=threshold,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return [
        _search_response(match)
        for match in matches
    ]


@router.get(
    "/documents/{document_id}",
    response_model=KnowledgeDocumentDetailResponse,
)
def get_document(
    current_user_id: CurrentUserId,
    service: Annotated[
        KnowledgeService,
        Depends(get_knowledge_service),
    ],
    document_id: int = Path(
        ge=1,
    ),
) -> KnowledgeDocumentDetailResponse:
    document = service.get_document(
        user_id=current_user_id,
        document_id=document_id,
    )

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found.",
        )

    return _document_detail_response(
        document
    )


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_document(
    current_user_id: CurrentUserId,
    service: Annotated[
        KnowledgeService,
        Depends(get_knowledge_service),
    ],
    document_id: int = Path(
        ge=1,
    ),
) -> Response:
    deleted = service.delete_document(
        user_id=current_user_id,
        document_id=document_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found.",
        )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )
