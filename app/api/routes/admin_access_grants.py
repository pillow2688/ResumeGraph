from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from app.api.dependencies.admin_auth import get_current_admin
from app.core.exceptions import (
    AccessControlUnavailableResponseError,
    AccessGrantNotFoundResponseError,
    InvalidAccessGrantRequestResponseError,
    InvalidProjectScopeResponseError,
)
from app.schemas.access_grant import (
    AccessGrantCreateRequest,
    AccessGrantCreateResponse,
    AccessGrantMetadata,
)
from app.schemas.admin_auth import AdminPrincipal
from app.schemas.error import ErrorResponse
from app.services.access_grant import (
    AccessControlUnavailableError,
    AccessGrantNotFoundError,
    AccessGrantService,
    InvalidAccessGrantRequestError,
    InvalidProjectScopeError,
)

router = APIRouter(prefix="/api/v1/admin/access-grants", tags=["admin-access-grants"])

GRANT_ERROR_RESPONSES = {
    401: {"description": "Administrator authentication required", "model": ErrorResponse},
    422: {"description": "Invalid grant or project scope", "model": ErrorResponse},
    503: {"description": "Access-control dependency unavailable", "model": ErrorResponse},
}


def _service(request: Request) -> AccessGrantService:
    return cast(AccessGrantService, request.app.state.access_grant_service)


@router.post(
    "",
    response_model=AccessGrantCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses=GRANT_ERROR_RESPONSES,
)
async def create_access_grant(
    payload: AccessGrantCreateRequest,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> AccessGrantCreateResponse:
    try:
        result = await _service(request).create_grant(
            name=payload.name,
            expires_at=payload.expires_at,
            max_requests=payload.max_requests,
            project_ids=payload.project_ids,
        )
    except InvalidAccessGrantRequestError as error:
        raise InvalidAccessGrantRequestResponseError from error
    except InvalidProjectScopeError as error:
        raise InvalidProjectScopeResponseError from error
    except AccessControlUnavailableError as error:
        raise AccessControlUnavailableResponseError from error
    return AccessGrantCreateResponse(grant=result.grant, access_token=result.access_token)


@router.get("", response_model=list[AccessGrantMetadata], responses=GRANT_ERROR_RESPONSES)
async def list_access_grants(
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> list[AccessGrantMetadata]:
    try:
        return await _service(request).list_grants()
    except AccessControlUnavailableError as error:
        raise AccessControlUnavailableResponseError from error


@router.get(
    "/{grant_id}",
    response_model=AccessGrantMetadata,
    responses={
        **GRANT_ERROR_RESPONSES,
        404: {"description": "Grant not found", "model": ErrorResponse},
    },
)
async def get_access_grant(
    grant_id: UUID,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> AccessGrantMetadata:
    try:
        return await _service(request).get_grant(grant_id)
    except AccessGrantNotFoundError as error:
        raise AccessGrantNotFoundResponseError from error
    except AccessControlUnavailableError as error:
        raise AccessControlUnavailableResponseError from error


@router.post(
    "/{grant_id}/revoke",
    response_model=AccessGrantMetadata,
    responses={
        **GRANT_ERROR_RESPONSES,
        404: {"description": "Grant not found", "model": ErrorResponse},
    },
)
async def revoke_access_grant(
    grant_id: UUID,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> AccessGrantMetadata:
    try:
        return await _service(request).revoke_grant(grant_id)
    except AccessGrantNotFoundError as error:
        raise AccessGrantNotFoundResponseError from error
    except AccessControlUnavailableError as error:
        raise AccessControlUnavailableResponseError from error
