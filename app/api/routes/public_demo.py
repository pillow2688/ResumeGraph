from typing import cast

from fastapi import APIRouter, Request, Response

from app.api.routes.recruiter_access import RECRUITER_COOKIE_PATH
from app.core.exceptions import (
    PublicDemoServiceUnavailableResponseError,
    PublicDemoUnavailableResponseError,
)
from app.schemas.error import ErrorResponse
from app.schemas.public_demo import PublicDemoSessionResponse, PublicDemoStatusResponse
from app.services.public_demo import (
    PublicDemoService,
    PublicDemoServiceUnavailableError,
    PublicDemoUnavailableError,
)

router = APIRouter(prefix="/api/v1/public", tags=["public-demo"])


def _service(request: Request) -> PublicDemoService:
    return cast(PublicDemoService, request.app.state.public_demo_service)


@router.get(
    "/demo",
    response_model=PublicDemoStatusResponse,
    response_model_exclude_none=True,
    responses={503: {"description": "Public Demo dependency unavailable", "model": ErrorResponse}},
)
async def get_public_demo(request: Request) -> PublicDemoStatusResponse:
    try:
        return await _service(request).get_public_status()
    except PublicDemoServiceUnavailableError as error:
        raise PublicDemoServiceUnavailableResponseError from error


@router.post(
    "/demo/session",
    response_model=PublicDemoSessionResponse,
    responses={
        409: {"description": "Public Demo is not open", "model": ErrorResponse},
        503: {"description": "Public Demo dependency unavailable", "model": ErrorResponse},
    },
)
async def create_public_demo_session(
    request: Request,
    response: Response,
) -> PublicDemoSessionResponse:
    try:
        result = await _service(request).create_public_session()
    except PublicDemoUnavailableError as error:
        raise PublicDemoUnavailableResponseError from error
    except PublicDemoServiceUnavailableError as error:
        raise PublicDemoServiceUnavailableResponseError from error

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
    return PublicDemoSessionResponse()
