from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Response,
    status,
)

from api.dependencies import CurrentUserId
from api.schemas.permission import (
    PermissionAction,
    PermissionResponse,
    PermissionSetRequest,
)
from services.permission_service import PermissionService
from services.audit_service import AuditService


router = APIRouter(
    prefix="/permissions",
    tags=["permissions"],
)


audit_service = AuditService()


def get_permission_service() -> PermissionService:
    return PermissionService()


def _permission_response(
    permission: dict,
) -> PermissionResponse:
    return PermissionResponse.model_validate(
        permission
    )


def _record_permission_audit(
    *,
    user_id: str,
    action: str,
    status: str,
    tool: str,
    permission_action: str,
    mode: str | None = None,
    resource_id: int | None = None,
) -> None:
    try:
        audit_service.record_event(
            event_type="authorization",
            action=action,
            status=status,
            user_id=user_id,
            resource_type="permission",
            resource_id=resource_id,
            metadata={
                "tool": tool,
                "permission_action": permission_action,
                "mode": mode,
            },
        )
    except Exception:
        return


_VALID_PERMISSION_ACTIONS = frozenset(
    PermissionAction.__args__
)


@router.get(
    "",
    response_model=list[PermissionResponse],
)
def list_permissions(
    current_user_id: CurrentUserId,
    permission_service: Annotated[
        PermissionService,
        Depends(get_permission_service),
    ],
) -> list[PermissionResponse]:
    permissions = permission_service.list_permissions(
        user_id=current_user_id,
    )

    return [
        _permission_response(
            permission
        )
        for permission in permissions
    ]


@router.put(
    "/{tool}/{action}",
    response_model=PermissionResponse,
)
def set_permission(
    request: PermissionSetRequest,
    current_user_id: CurrentUserId,
    permission_service: Annotated[
        PermissionService,
        Depends(get_permission_service),
    ],
    tool: str = Path(
        min_length=1,
        max_length=100,
    ),
    action: str = Path(
        min_length=1,
        max_length=50,
    ),
) -> PermissionResponse:
    normalized_tool = tool.strip().lower()
    normalized_action = action.strip().lower()

    if normalized_action not in _VALID_PERMISSION_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown permission action.",
        )

    try:
        permission_service.set_permission(
            user_id=current_user_id,
            tool=tool,
            action=action,
            mode=request.mode,
        )

        permissions = (
            permission_service.list_permissions(
                user_id=current_user_id,
            )
        )

        for permission in permissions:
            if (
                permission["tool"]
                == normalized_tool
                and permission["action"]
                == normalized_action
            ):
                _record_permission_audit(
                    user_id=current_user_id,
                    action="set",
                    status="success",
                    tool=normalized_tool,
                    permission_action=normalized_action,
                    mode=request.mode,
                    resource_id=permission["id"],
                )

                return _permission_response(
                    permission
                )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Permission could not be loaded after update.",
    )


@router.delete(
    "/{tool}/{action}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_permission(
    current_user_id: CurrentUserId,
    permission_service: Annotated[
        PermissionService,
        Depends(get_permission_service),
    ],
    tool: str = Path(
        min_length=1,
        max_length=100,
    ),
    action: str = Path(
        min_length=1,
        max_length=50,
    ),
) -> Response:
    try:
        deleted = permission_service.delete_permission(
            user_id=current_user_id,
            tool=tool,
            action=action,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission not found.",
        )

    _record_permission_audit(
        user_id=current_user_id,
        action="delete",
        status="success",
        tool=tool.strip().lower(),
        permission_action=action.strip().lower(),
    )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )
