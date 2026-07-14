from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.dependencies.admin_auth import get_admin_session_token, get_current_admin
from app.core.exceptions import (
    AdminAuthUnavailableResponseError,
    AdminLoginRateLimitedResponseError,
    InvalidCredentialsResponseError,
)
from app.schemas.admin_auth import AdminLoginRequest, AdminLoginResponse, AdminPrincipal
from app.schemas.error import ErrorResponse
from app.services.admin_auth import (
    AdminAuthService,
    AdminAuthUnavailableError,
    AdminLoginRateLimitedError,
    InvalidCredentialsError,
)

router = APIRouter(prefix="/api/v1/admin/auth", tags=["admin-auth"])
ADMIN_COOKIE_PATH = "/api/v1/admin"

AUTH_ERROR_RESPONSES = {
    401: {"description": "Administrator authentication failed", "model": ErrorResponse},
    422: {"description": "Invalid request", "model": ErrorResponse},
    429: {"description": "Administrator login is rate limited", "model": ErrorResponse},
    503: {"description": "Authentication dependency unavailable", "model": ErrorResponse},
}


@router.post(
    "/login",
    response_model=AdminLoginResponse,
    responses=AUTH_ERROR_RESPONSES,
)
async def login(
    credentials: AdminLoginRequest,
    request: Request,
    response: Response,
) -> AdminLoginResponse:
    service = cast(AdminAuthService, request.app.state.admin_auth_service)
    client_host = request.client.host if request.client is not None else "unknown"
    try:
        result = await service.login(
            credentials.username,
            credentials.password,
            client_host,
        )
    except InvalidCredentialsError as error:
        raise InvalidCredentialsResponseError from error
    except AdminLoginRateLimitedError as error:
        raise AdminLoginRateLimitedResponseError from error
    except AdminAuthUnavailableError as error:
        raise AdminAuthUnavailableResponseError from error

    settings = request.app.state.settings
    response.set_cookie(
        key=settings.admin_session_cookie_name,
        value=result.session_token,
        max_age=settings.admin_session_ttl_seconds,
        path=ADMIN_COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return AdminLoginResponse(admin=result.principal)


@router.get(
    "/me",
    response_model=AdminPrincipal,
    responses={
        401: {"description": "Administrator authentication required", "model": ErrorResponse},
        503: {"description": "Authentication dependency unavailable", "model": ErrorResponse},
    },
)
async def me(
    current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> AdminPrincipal:
    return current_admin


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        503: {"description": "Authentication dependency unavailable", "model": ErrorResponse}
    },
)
async def logout(
    request: Request,
    session_token: Annotated[str | None, Depends(get_admin_session_token)],
) -> Response:
    if session_token is not None:
        service = cast(AdminAuthService, request.app.state.admin_auth_service)
        try:
            await service.logout(session_token)
        except AdminAuthUnavailableError as error:
            raise AdminAuthUnavailableResponseError from error

    settings = request.app.state.settings
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        key=settings.admin_session_cookie_name,
        path=ADMIN_COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response
