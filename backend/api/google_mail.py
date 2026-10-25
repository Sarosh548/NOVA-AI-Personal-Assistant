from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import CurrentUserId
from config import get_settings
from services.google_mail_oauth_service import GoogleMailOAuthService


router = APIRouter(
    prefix="/integrations/google/mail",
    tags=["google-mail"],
)


def get_google_mail_oauth_service() -> GoogleMailOAuthService:
    return GoogleMailOAuthService(settings=get_settings())


@router.get("/status")
def get_google_mail_status(
    current_user_id: CurrentUserId,
    service: Annotated[
        GoogleMailOAuthService,
        Depends(get_google_mail_oauth_service),
    ],
) -> dict:
    connection = service.get_connection(user_id=current_user_id)
    return {
        "configured": service.is_configured,
        "connected": connection is not None,
        "provider": "google",
        "email": connection["email"] if connection else None,
        "scopes": connection["scopes"] if connection else None,
    }


@router.get("/connect")
def connect_google_mail(
    current_user_id: CurrentUserId,
    service: Annotated[
        GoogleMailOAuthService,
        Depends(get_google_mail_oauth_service),
    ],
) -> dict:
    try:
        return {
            "authorization_url": service.build_authorization_url(
                user_id=current_user_id,
            ),
        }
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.get("/messages")
def list_google_mail_messages(
    current_user_id: CurrentUserId,
    service: Annotated[
        GoogleMailOAuthService,
        Depends(get_google_mail_oauth_service),
    ],
    q: str | None = None,
    max_results: int = 5,
    include_body: bool = False,
) -> dict:
    if max_results < 1 or max_results > service.MAX_LIST_RESULTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"max_results must be between 1 and {service.MAX_LIST_RESULTS}.",
        )
    try:
        return service.list_messages(
            user_id=current_user_id,
            query=q,
            max_results=max_results,
            include_body=include_body,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/messages/{message_id}")
def get_google_mail_message(
    message_id: str,
    current_user_id: CurrentUserId,
    service: Annotated[
        GoogleMailOAuthService,
        Depends(get_google_mail_oauth_service),
    ],
) -> dict:
    try:
        return service.get_message(
            user_id=current_user_id,
            message_id=message_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.delete("")
def disconnect_google_mail(
    current_user_id: CurrentUserId,
    service: Annotated[
        GoogleMailOAuthService,
        Depends(get_google_mail_oauth_service),
    ],
) -> dict:
    return {
        "disconnected": service.disconnect(
            user_id=current_user_id,
        ),
    }
