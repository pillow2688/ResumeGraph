from typing import Annotated, cast

from fastapi import Depends, Request

from app.core.exceptions import (
    AdminAuthUnavailableResponseError,
    AuthenticationRequiredResponseError,
)
from app.schemas.admin_auth import AdminPrincipal
from app.services.admin_auth import (
    AdminAuthService,
    AdminAuthUnavailableError,
    InvalidAdminSessionError,
)


def get_admin_session_token(request: Request) -> str | None:
    cookie_name = request.app.state.settings.admin_session_cookie_name
    return request.cookies.get(cookie_name)


async def get_current_admin(
    request: Request,
    session_token: Annotated[str | None, Depends(get_admin_session_token)],
) -> AdminPrincipal:
    if session_token is None:
        raise AuthenticationRequiredResponseError
    service = cast(AdminAuthService, request.app.state.admin_auth_service)
    try:
        return await service.get_current_admin(session_token)
    except InvalidAdminSessionError as error:
        raise AuthenticationRequiredResponseError from error
    except AdminAuthUnavailableError as error:
        raise AdminAuthUnavailableResponseError from error
