from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.api.dependencies.recruiter_auth import get_current_recruiter
from app.core.exceptions import (
    InterviewProjectScopeResponseError,
    InterviewQuotaExhaustedResponseError,
    InterviewUnavailableResponseError,
)
from app.schemas.access_grant import RecruiterPrincipal
from app.schemas.error import ErrorResponse
from app.schemas.interview import InterviewAskRequest, InterviewAskResponse
from app.services.interview import (
    InterviewOutputInvalidError,
    InterviewProjectScopeError,
    InterviewQuotaExhaustedError,
    InterviewService,
    InterviewUnavailableError,
)

router = APIRouter(prefix="/api/v1/interview", tags=["recruiter-interview"])


def _service(request: Request) -> InterviewService:
    return cast(InterviewService, request.app.state.interview_service)


@router.post(
    "/ask",
    response_model=InterviewAskResponse,
    responses={
        401: {"description": "Recruiter authentication required", "model": ErrorResponse},
        403: {"description": "Project scope forbidden", "model": ErrorResponse},
        429: {"description": "Request quota exhausted", "model": ErrorResponse},
        503: {"description": "Interview temporarily unavailable", "model": ErrorResponse},
    },
)
async def ask_interview_question(
    payload: InterviewAskRequest,
    request: Request,
    current_recruiter: Annotated[RecruiterPrincipal, Depends(get_current_recruiter)],
) -> InterviewAskResponse:
    try:
        return await _service(request).ask(
            principal=current_recruiter,
            question=payload.question,
            requested_project_ids=payload.project_ids,
        )
    except InterviewProjectScopeError as error:
        raise InterviewProjectScopeResponseError from error
    except InterviewQuotaExhaustedError as error:
        raise InterviewQuotaExhaustedResponseError from error
    except (InterviewOutputInvalidError, InterviewUnavailableError) as error:
        raise InterviewUnavailableResponseError from error
