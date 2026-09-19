from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)

from api.dependencies import CurrentUserId
from api.schemas.conversation import (
    ConversationCreatedResponse,
    ConversationCreateRequest,
    ConversationMessageResponse,
    ConversationMessagesResponse,
    ConversationResponse,
    ConversationStateResponse,
    ConversationUpdateRequest,
    ConversationUpdateResponse,
)
from services.conversation_service import (
    ConversationService,
)


router = APIRouter(
    prefix="/conversations",
    tags=["conversations"],
)


def get_conversation_service() -> ConversationService:
    return ConversationService()


@router.post(
    "",
    response_model=ConversationCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    request: ConversationCreateRequest,
    current_user_id: CurrentUserId,
    conversation_service: Annotated[
        ConversationService,
        Depends(get_conversation_service),
    ],
) -> ConversationCreatedResponse:
    title = (
        request.title
        if request.title is not None
        else "New Conversation"
    )

    conversation_id = (
        conversation_service.create_conversation(
            user_id=current_user_id,
            title=title,
        )
    )

    return ConversationCreatedResponse(
        id=conversation_id,
    )


@router.get(
    "",
    response_model=list[ConversationResponse],
)
def get_conversations(
    current_user_id: CurrentUserId,
    conversation_service: Annotated[
        ConversationService,
        Depends(get_conversation_service),
    ],
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),
) -> list[ConversationResponse]:
    conversations = (
        conversation_service.get_conversations(
            user_id=current_user_id,
            limit=limit,
        )
    )

    return [
        ConversationResponse.model_validate(
            conversation
        )
        for conversation in conversations
    ]


@router.get(
    "/{conversation_id}/messages",
    response_model=ConversationMessagesResponse,
)
def get_conversation_messages(
    conversation_id: int,
    current_user_id: CurrentUserId,
    conversation_service: Annotated[
        ConversationService,
        Depends(get_conversation_service),
    ],
    limit: int = Query(
        default=100,
        ge=1,
        le=100,
    ),
) -> ConversationMessagesResponse:
    messages = conversation_service.get_history(
        user_id=current_user_id,
        conversation_id=conversation_id,
        limit=limit,
    )

    return ConversationMessagesResponse(
        conversation_id=conversation_id,
        messages=[
            ConversationMessageResponse(
                role=message["role"],
                content=message["content"],
            )
            for message in messages
        ],
    )


@router.get(
    "/{conversation_id}/state",
    response_model=ConversationStateResponse,
)
def get_conversation_state(
    conversation_id: int,
    current_user_id: CurrentUserId,
    conversation_service: Annotated[
        ConversationService,
        Depends(get_conversation_service),
    ],
) -> ConversationStateResponse:
    conversation_state = (
        conversation_service.get_conversation_state(
            user_id=current_user_id,
            conversation_id=conversation_id,
        )
    )

    return ConversationStateResponse(
        conversation_id=conversation_id,
        state=conversation_state["state"],
        last_role=conversation_state[
            "last_role"
        ],
        should_listen=conversation_state[
            "should_listen"
        ],
    )


@router.patch(
    "/{conversation_id}",
    response_model=ConversationUpdateResponse,
)
def update_conversation(
    conversation_id: int,
    request: ConversationUpdateRequest,
    current_user_id: CurrentUserId,
    conversation_service: Annotated[
        ConversationService,
        Depends(get_conversation_service),
    ],
) -> ConversationUpdateResponse:
    updated = (
        conversation_service.update_conversation_title(
            conversation_id=conversation_id,
            user_id=current_user_id,
            title=request.title,
        )
    )

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    return ConversationUpdateResponse(
        updated=True,
    )


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation(
    conversation_id: int,
    current_user_id: CurrentUserId,
    conversation_service: Annotated[
        ConversationService,
        Depends(get_conversation_service),
    ],
) -> Response:
    deleted = (
        conversation_service.delete_conversation(
            user_id=current_user_id,
            conversation_id=conversation_id,
        )
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )