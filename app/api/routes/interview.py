import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse

from app.api.dependencies.recruiter_auth import get_current_recruiter
from app.core.exceptions import (
    InterviewConversationBusyResponseError,
    InterviewConversationNotFoundResponseError,
    InterviewProjectScopeResponseError,
    InterviewQuotaExhaustedResponseError,
    InterviewRequestConflictResponseError,
    InterviewUnavailableResponseError,
)
from app.schemas.access_grant import RecruiterPrincipal
from app.schemas.error import ErrorResponse
from app.schemas.interview import InterviewAskRequest, InterviewAskResponse
from app.schemas.interview_conversation import (
    ConversationAskRequest,
    ConversationAskResponse,
    ConversationCreateResponse,
)
from app.services.interview import (
    InterviewOutputInvalidError,
    InterviewProjectScopeError,
    InterviewQuotaExhaustedError,
    InterviewService,
    InterviewUnavailableError,
)
from app.services.interview_workflow import (
    ConversationBusyError,
    ConversationNotFoundError,
    ConversationPreviousRequestFailedError,
    ConversationQuotaExhaustedError,
    ConversationRequestMismatchError,
    ConversationWorkflowUnavailableError,
    InterviewWorkflowService,
)

router = APIRouter(prefix="/api/v1/interview", tags=["recruiter-interview"])


def _service(request: Request) -> InterviewService:
    return cast(InterviewService, request.app.state.interview_service)


def _workflow_service(request: Request) -> InterviewWorkflowService:
    return cast(InterviewWorkflowService, request.app.state.interview_workflow_service)


def _session_token(request: Request) -> str:
    settings = request.app.state.settings
    token = request.cookies.get(settings.recruiter_session_cookie_name)
    if not token:
        raise InterviewConversationNotFoundResponseError
    return token


def _raise_workflow_error(error: Exception) -> None:
    if isinstance(error, ConversationNotFoundError):
        raise InterviewConversationNotFoundResponseError from error
    if isinstance(error, ConversationBusyError):
        raise InterviewConversationBusyResponseError from error
    if isinstance(
        error,
        (ConversationPreviousRequestFailedError, ConversationRequestMismatchError),
    ):
        raise InterviewRequestConflictResponseError from error
    if isinstance(error, ConversationQuotaExhaustedError):
        raise InterviewQuotaExhaustedResponseError from error
    if isinstance(error, ConversationWorkflowUnavailableError):
        raise InterviewUnavailableResponseError from error
    raise error


def _sse(event_type: str, payload: dict[str, object]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


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


@router.post(
    "/conversations",
    response_model=ConversationCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"description": "Recruiter authentication required", "model": ErrorResponse},
        503: {"description": "Interview temporarily unavailable", "model": ErrorResponse},
    },
)
async def create_interview_conversation(
    request: Request,
    current_recruiter: Annotated[RecruiterPrincipal, Depends(get_current_recruiter)],
) -> ConversationCreateResponse:
    try:
        return await _workflow_service(request).create_conversation(
            principal=current_recruiter,
            session_token=_session_token(request),
        )
    except ConversationWorkflowUnavailableError as error:
        raise InterviewUnavailableResponseError from error


@router.post(
    "/conversations/{conversation_id}/ask",
    response_model=ConversationAskResponse,
    responses={
        401: {"description": "Recruiter authentication required", "model": ErrorResponse},
        404: {"description": "Conversation unavailable", "model": ErrorResponse},
        409: {"description": "Conversation or request conflict", "model": ErrorResponse},
        429: {"description": "Request quota exhausted", "model": ErrorResponse},
        503: {"description": "Interview temporarily unavailable", "model": ErrorResponse},
    },
)
async def ask_conversation_question(
    conversation_id: UUID,
    payload: ConversationAskRequest,
    request: Request,
    current_recruiter: Annotated[RecruiterPrincipal, Depends(get_current_recruiter)],
) -> ConversationAskResponse:
    try:
        return await _workflow_service(request).ask(
            principal=current_recruiter,
            session_token=_session_token(request),
            conversation_id=conversation_id,
            request_id=payload.request_id,
            question=payload.question,
            requested_project_ids=payload.project_ids,
        )
    except (
        ConversationNotFoundError,
        ConversationBusyError,
        ConversationPreviousRequestFailedError,
        ConversationRequestMismatchError,
        ConversationQuotaExhaustedError,
        ConversationWorkflowUnavailableError,
    ) as error:
        _raise_workflow_error(error)


@router.post(
    "/conversations/{conversation_id}/ask/stream",
    response_class=StreamingResponse,
    responses={
        401: {"description": "Recruiter authentication required", "model": ErrorResponse},
        200: {"description": "Public Agent progress stream"},
    },
)
async def stream_conversation_question(
    conversation_id: UUID,
    payload: ConversationAskRequest,
    request: Request,
    current_recruiter: Annotated[RecruiterPrincipal, Depends(get_current_recruiter)],
) -> StreamingResponse:
    session_token = _session_token(request)
    service = _workflow_service(request)

    async def event_stream():
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()

        async def event_sink(event: dict[str, object]) -> None:
            await queue.put(event)

        workflow_task = asyncio.create_task(
            service.ask(
                principal=current_recruiter,
                session_token=session_token,
                conversation_id=conversation_id,
                request_id=payload.request_id,
                question=payload.question,
                requested_project_ids=payload.project_ids,
                event_sink=event_sink,
            )
        )
        try:
            while True:
                if await request.is_disconnected():
                    workflow_task.cancel()
                    break
                get_task = asyncio.create_task(queue.get())
                done, _pending = await asyncio.wait(
                    {get_task, workflow_task},
                    timeout=15,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if get_task in done:
                    event = get_task.result()
                    if event.get("event_type") != "answer_completed":
                        yield _sse(str(event["event_type"]), event)
                else:
                    get_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await get_task

                if workflow_task in done:
                    while not queue.empty():
                        event = queue.get_nowait()
                        if event.get("event_type") != "answer_completed":
                            yield _sse(str(event["event_type"]), event)
                    try:
                        response = workflow_task.result()
                    except (
                        ConversationNotFoundError,
                        ConversationBusyError,
                        ConversationPreviousRequestFailedError,
                        ConversationRequestMismatchError,
                        ConversationQuotaExhaustedError,
                        ConversationWorkflowUnavailableError,
                    ) as error:
                        error_messages = {
                            ConversationNotFoundError: "当前对话已过期，请新建对话。",
                            ConversationBusyError: "当前对话正在处理另一个问题，请稍候。",
                            ConversationPreviousRequestFailedError: (
                                "该请求未能完成，请使用新的请求重新提交。"
                            ),
                            ConversationRequestMismatchError: "请求标识与问题不匹配。",
                            ConversationQuotaExhaustedError: "当前访问的提问额度已用尽。",
                            ConversationWorkflowUnavailableError: (
                                "面试回答服务暂时不可用，请稍后重试。"
                            ),
                        }
                        message = next(
                            value
                            for error_type, value in error_messages.items()
                            if isinstance(error, error_type)
                        )
                        failure = {
                            "event_type": "request_failed",
                            "public_message": message,
                            "timestamp": datetime.now(UTC).isoformat(),
                            "progress": 100,
                        }
                        yield _sse("request_failed", failure)
                    else:
                        completed = {
                            "event_type": "answer_completed",
                            "public_message": "回答已完成",
                            "timestamp": datetime.now(UTC).isoformat(),
                            "progress": 100,
                            "response": response.model_dump(mode="json"),
                        }
                        yield _sse("answer_completed", completed)
                    break
                if not done:
                    heartbeat = {
                        "event_type": "heartbeat",
                        "public_message": "连接保持中",
                        "timestamp": datetime.now(UTC).isoformat(),
                        "progress": 0,
                    }
                    yield _sse("heartbeat", heartbeat)
        finally:
            if not workflow_task.done():
                workflow_task.cancel()
                with suppress(asyncio.CancelledError):
                    await workflow_task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={
        401: {"description": "Recruiter authentication required", "model": ErrorResponse},
        404: {"description": "Conversation unavailable", "model": ErrorResponse},
        503: {"description": "Interview temporarily unavailable", "model": ErrorResponse},
    },
)
async def delete_interview_conversation(
    conversation_id: UUID,
    request: Request,
    current_recruiter: Annotated[RecruiterPrincipal, Depends(get_current_recruiter)],
) -> Response:
    try:
        await _workflow_service(request).delete_conversation(
            principal=current_recruiter,
            session_token=_session_token(request),
            conversation_id=conversation_id,
        )
    except (ConversationNotFoundError, ConversationWorkflowUnavailableError) as error:
        _raise_workflow_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
