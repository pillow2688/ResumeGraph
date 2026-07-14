from typing import Annotated, cast

from fastapi import Depends, Request

from app.core.exceptions import (
    AccessControlUnavailableResponseError,
    RecruiterAuthenticationRequiredResponseError,
)
from app.schemas.access_grant import RecruiterPrincipal
from app.services.access_grant import (
    AccessControlUnavailableError,
    AccessGrantService,
    InvalidRecruiterSessionError,
)


def get_recruiter_session_token(request: Request) -> str | None:
    cookie_name = request.app.state.settings.recruiter_session_cookie_name
    return request.cookies.get(cookie_name)


async def get_current_recruiter(
    request: Request,
    session_token: Annotated[str | None, Depends(get_recruiter_session_token)],
) -> RecruiterPrincipal:
    if session_token is None:
        raise RecruiterAuthenticationRequiredResponseError
    service = cast(AccessGrantService, request.app.state.access_grant_service)
    try:
        return await service.get_current_recruiter(session_token)
    except InvalidRecruiterSessionError as error:
        raise RecruiterAuthenticationRequiredResponseError from error
    except AccessControlUnavailableError as error:
        raise AccessControlUnavailableResponseError from error
