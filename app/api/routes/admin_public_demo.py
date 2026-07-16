from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.api.dependencies.admin_auth import get_current_admin
from app.core.exceptions import (
    InvalidPublicDemoConfigResponseError,
    PublicDemoServiceUnavailableResponseError,
)
from app.schemas.admin_auth import AdminPrincipal
from app.schemas.error import ErrorResponse
from app.schemas.public_demo import PublicDemoAdminResponse, PublicDemoUpdateRequest
from app.services.public_demo import (
    InvalidPublicDemoConfigError,
    PublicDemoService,
    PublicDemoServiceUnavailableError,
)

router = APIRouter(prefix="/api/v1/admin/public-demo", tags=["admin-public-demo"])

PUBLIC_DEMO_ADMIN_RESPONSES = {
    401: {"description": "Administrator authentication required", "model": ErrorResponse},
    422: {"description": "Invalid Public Demo configuration", "model": ErrorResponse},
    503: {"description": "Public Demo dependency unavailable", "model": ErrorResponse},
}


def _service(request: Request) -> PublicDemoService:
    return cast(PublicDemoService, request.app.state.public_demo_service)


@router.get(
    "",
    response_model=PublicDemoAdminResponse,
    response_model_exclude_none=True,
    responses=PUBLIC_DEMO_ADMIN_RESPONSES,
)
async def get_public_demo_config(
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> PublicDemoAdminResponse:
    try:
        return await _service(request).get_admin_config()
    except PublicDemoServiceUnavailableError as error:
        raise PublicDemoServiceUnavailableResponseError from error


@router.put(
    "",
    response_model=PublicDemoAdminResponse,
    response_model_exclude_none=True,
    responses=PUBLIC_DEMO_ADMIN_RESPONSES,
)
async def update_public_demo_config(
    payload: PublicDemoUpdateRequest,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> PublicDemoAdminResponse:
    try:
        return await _service(request).update_config(
            candidate_name=payload.candidate_name,
            default_access_grant_id=payload.default_access_grant_id,
            enabled=payload.enabled,
        )
    except InvalidPublicDemoConfigError as error:
        raise InvalidPublicDemoConfigResponseError from error
    except PublicDemoServiceUnavailableError as error:
        raise PublicDemoServiceUnavailableResponseError from error
