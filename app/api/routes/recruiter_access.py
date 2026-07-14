from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.dependencies.recruiter_auth import (
    get_current_recruiter,
    get_recruiter_session_token,
)
from app.core.exceptions import (
    AccessControlUnavailableResponseError,
    AccessExchangeRateLimitedResponseError,
    InvalidAccessGrantResponseError,
)
from app.schemas.access_grant import (
    AccessTokenExchangeRequest,
    RecruiterAccessResponse,
    RecruiterExchangeResponse,
    RecruiterPrincipal,
)
from app.schemas.error import ErrorResponse
from app.services.access_grant import (
    AccessControlUnavailableError,
    AccessExchangeRateLimitedError,
    AccessGrantService,
    InvalidAccessGrantError,
)

router = APIRouter(prefix="/api/v1/access", tags=["recruiter-access"])
RECRUITER_COOKIE_PATH = "/api/v1"


def _service(request: Request) -> AccessGrantService:
    return cast(AccessGrantService, request.app.state.access_grant_service)


@router.post(
    "/exchange",
    response_model=RecruiterExchangeResponse,
    responses={
        401: {"description": "Invalid access grant", "model": ErrorResponse},
        429: {"description": "Access exchange rate limited", "model": ErrorResponse},
        503: {"description": "Access-control dependency unavailable", "model": ErrorResponse},
    },
)
async def exchange_access_token(
    payload: AccessTokenExchangeRequest,
    request: Request,
    response: Response,
) -> RecruiterExchangeResponse:
    client_host = request.client.host if request.client is not None else "unknown"
    try:
        result = await _service(request).exchange_access_token(
            payload.access_token,
            client_host,
        )
    except InvalidAccessGrantError as error:
        raise InvalidAccessGrantResponseError from error
    except AccessExchangeRateLimitedError as error:
        raise AccessExchangeRateLimitedResponseError from error
    except AccessControlUnavailableError as error:
        raise AccessControlUnavailableResponseError from error

    settings = request.app.state.settings
    response.set_cookie(
        key=settings.recruiter_session_cookie_name,
        value=result.session_token,
        max_age=result.ttl_seconds,
        expires=result.expires_at,
        path=RECRUITER_COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return RecruiterExchangeResponse(
        recruiter=RecruiterAccessResponse.from_principal(result.principal)
    )


@router.get(
    "/me",
    response_model=RecruiterAccessResponse,
    responses={
        401: {"description": "Recruiter authentication required", "model": ErrorResponse},
        503: {"description": "Access-control dependency unavailable", "model": ErrorResponse},
    },
)
async def me(
    current_recruiter: Annotated[RecruiterPrincipal, Depends(get_current_recruiter)],
) -> RecruiterAccessResponse:
    return RecruiterAccessResponse.from_principal(current_recruiter)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        503: {"description": "Access-control dependency unavailable", "model": ErrorResponse}
    },
)
async def logout(
    request: Request,
    session_token: Annotated[str | None, Depends(get_recruiter_session_token)],
) -> Response:
    if session_token is not None:
        try:
            await _service(request).logout(session_token)
        except AccessControlUnavailableError as error:
            raise AccessControlUnavailableResponseError from error

    settings = request.app.state.settings
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        key=settings.recruiter_session_cookie_name,
        path=RECRUITER_COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response
