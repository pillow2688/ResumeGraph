from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.dependencies.admin_auth import get_current_admin
from app.core.exceptions import (
    AdminDeletionForbiddenResponseError,
    AdminUserManagementUnavailableResponseError,
    AdminUsernameExistsResponseError,
    ManagedAdminNotFoundResponseError,
)
from app.schemas.admin_auth import AdminPrincipal
from app.schemas.admin_user import AdminUserCreateRequest, AdminUserResponse
from app.schemas.error import ErrorResponse
from app.services.admin_auth import AdminUsernameExistsError
from app.services.admin_user_management import (
    AdminUserManagementService,
    AdminUserManagementUnavailableError,
    CannotDeleteCurrentAdminError,
    LastAdminDeletionError,
    ManagedAdminNotFoundError,
)

router = APIRouter(prefix="/api/v1/admin/users", tags=["admin-users"])

ERROR_RESPONSES = {
    401: {"description": "Administrator authentication required", "model": ErrorResponse},
    409: {"description": "Administrator conflict", "model": ErrorResponse},
    422: {"description": "Invalid request", "model": ErrorResponse},
    503: {"description": "Administrator persistence unavailable", "model": ErrorResponse},
}


def _service(request: Request) -> AdminUserManagementService:
    return cast(AdminUserManagementService, request.app.state.admin_user_service)


def _raise_service_error(error: Exception) -> None:
    if isinstance(error, AdminUsernameExistsError):
        raise AdminUsernameExistsResponseError from error
    if isinstance(error, ManagedAdminNotFoundError):
        raise ManagedAdminNotFoundResponseError from error
    if isinstance(error, CannotDeleteCurrentAdminError):
        raise AdminDeletionForbiddenResponseError(
            code="cannot_delete_current_admin",
            message="The current administrator cannot delete their own account.",
        ) from error
    if isinstance(error, LastAdminDeletionError):
        raise AdminDeletionForbiddenResponseError(
            code="cannot_delete_last_admin",
            message="The final administrator account cannot be deleted.",
        ) from error
    if isinstance(error, AdminUserManagementUnavailableError):
        raise AdminUserManagementUnavailableResponseError from error
    raise error


@router.get("", response_model=list[AdminUserResponse], responses=ERROR_RESPONSES)
async def list_admins(
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> list[AdminUserResponse]:
    try:
        return await _service(request).list_admins()
    except AdminUserManagementUnavailableError as error:
        _raise_service_error(error)


@router.post(
    "",
    response_model=AdminUserResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
async def create_admin(
    payload: AdminUserCreateRequest,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> AdminUserResponse:
    try:
        return await _service(request).create_admin(payload.username, payload.password)
    except (
        AdminUsernameExistsError,
        AdminUserManagementUnavailableError,
    ) as error:
        _raise_service_error(error)


@router.delete(
    "/{admin_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        **ERROR_RESPONSES,
        404: {"description": "Administrator not found", "model": ErrorResponse},
    },
)
async def delete_admin(
    admin_id: UUID,
    request: Request,
    current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> Response:
    try:
        await _service(request).delete_admin(
            target_admin_id=admin_id,
            current_admin_id=current_admin.id,
        )
    except (
        ManagedAdminNotFoundError,
        CannotDeleteCurrentAdminError,
        LastAdminDeletionError,
        AdminUserManagementUnavailableError,
    ) as error:
        _raise_service_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
