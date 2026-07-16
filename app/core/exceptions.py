import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.error import ErrorBody, ErrorResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """A controlled application error safe to serialize for an API client."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = dict(details) if details is not None else None


class ServiceNotReadyError(AppError):
    def __init__(self, *, details: Mapping[str, Any]) -> None:
        super().__init__(
            status_code=503,
            code="service_not_ready",
            message="Service dependencies are unavailable.",
            details=details,
        )


class InvalidCredentialsResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=401,
            code="invalid_credentials",
            message="Invalid administrator credentials.",
        )


class AuthenticationRequiredResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=401,
            code="authentication_required",
            message="Administrator authentication is required.",
        )


class AdminLoginRateLimitedResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=429,
            code="admin_login_rate_limited",
            message="Too many administrator login failures. Try again later.",
        )


class AdminAuthUnavailableResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="service_unavailable",
            message="Administrator authentication is temporarily unavailable.",
        )


class AdminUsernameExistsResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="admin_username_exists",
            message="Administrator username already exists.",
        )


class ManagedAdminNotFoundResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=404,
            code="admin_not_found",
            message="Administrator not found.",
        )


class AdminDeletionForbiddenResponseError(AppError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(status_code=409, code=code, message=message)


class AdminUserManagementUnavailableResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="service_unavailable",
            message="Administrator management is temporarily unavailable.",
        )


class InvalidAccessGrantResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=401,
            code="invalid_access_grant",
            message="The access grant is invalid or unavailable.",
        )


class RecruiterAuthenticationRequiredResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=401,
            code="recruiter_authentication_required",
            message="Recruiter authentication is required.",
        )


class AccessExchangeRateLimitedResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=429,
            code="access_exchange_rate_limited",
            message="Too many failed access attempts. Try again later.",
        )


class AccessControlUnavailableResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="service_unavailable",
            message="Recruiter access control is temporarily unavailable.",
        )


class InterviewProjectScopeResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=403,
            code="project_scope_forbidden",
            message="The requested project scope is not authorized.",
        )


class InterviewQuotaExhaustedResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=429,
            code="request_quota_exhausted",
            message="The access grant request quota is exhausted.",
        )


class InterviewUnavailableResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="interview_unavailable",
            message="Interview answering is temporarily unavailable.",
        )


class InterviewConversationNotFoundResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=404,
            code="conversation_not_found",
            message="The interview conversation is unavailable or expired.",
        )


class InterviewConversationBusyResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="conversation_busy",
            message="The interview conversation is processing another request.",
        )


class InterviewRequestConflictResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="interview_request_conflict",
            message="The request identifier cannot be reused for this question.",
        )


class InvalidAccessGrantRequestResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=422,
            code="invalid_access_grant_request",
            message="The access grant request is invalid.",
        )


class InvalidProjectScopeResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=422,
            code="invalid_project_scope",
            message="One or more requested projects do not exist.",
        )


class AccessGrantNotFoundResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=404,
            code="not_found",
            message="Resource not found.",
        )


class InvalidProjectRequestResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=422,
            code="invalid_project_request",
            message="The project request is invalid.",
        )


class ProjectNotFoundResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=404,
            code="project_not_found",
            message="Project not found.",
        )


class ProjectInUseResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="project_in_use",
            message="Project is in use and cannot be deleted.",
        )


class ProjectUnavailableResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="service_unavailable",
            message="Project management is temporarily unavailable.",
        )


class InvalidDocumentRequestResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=422,
            code="invalid_document_request",
            message="The knowledge document request is invalid.",
        )


class DocumentNotFoundResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=404,
            code="document_not_found",
            message="Knowledge document not found.",
        )


class DocumentVersionNotFoundResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=404,
            code="document_version_not_found",
            message="Document version not found.",
        )


class DuplicateDocumentVersionResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="duplicate_document_version",
            message="An identical document version already exists.",
        )


class UnsupportedMarkdownFileResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=415,
            code="unsupported_markdown_file",
            message="Only .md files are supported.",
        )


class MarkdownTooLargeResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=413,
            code="markdown_too_large",
            message="The Markdown content exceeds the configured size limit.",
        )


class InvalidMarkdownEncodingResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=422,
            code="invalid_markdown_encoding",
            message="The Markdown file must use valid UTF-8 encoding.",
        )


class InvalidMarkdownContentResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=422,
            code="invalid_markdown_content",
            message="The Markdown content is invalid.",
        )


class KnowledgeDocumentUnavailableResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="service_unavailable",
            message="Knowledge document management is temporarily unavailable.",
        )


class DocumentVersionNotDeletableResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="document_version_not_deletable",
            message="The document version cannot be permanently deleted in its current state.",
        )


class ActiveDocumentJobResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="active_document_job",
            message="The document has an active processing job.",
        )


class DocumentConfirmationMismatchResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="document_confirmation_mismatch",
            message="The permanent deletion confirmation does not match.",
        )


class IngestionJobNotFoundResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=404,
            code="ingestion_job_not_found",
            message="Document processing job not found.",
        )


class DocumentVersionNotProcessableResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="document_version_not_processable",
            message="The document version is not available for processing.",
        )


class IngestionUnavailableResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="service_unavailable",
            message="Document processing is temporarily unavailable.",
        )


class DocumentChunkNotFoundResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=404,
            code="document_chunk_not_found",
            message="Document chunk not found.",
        )


class DocumentChunkNotEditableResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="document_chunk_not_editable",
            message="The document chunk cannot be changed in its current version state.",
        )


class KnowledgePublicationUnavailableResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="service_unavailable",
            message="Knowledge publication is temporarily unavailable.",
        )


class DocumentVersionNotPublishableResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="document_version_not_publishable",
            message="The document version is not ready to publish.",
        )


class PublicationIntegrityResponseError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="publication_integrity_failed",
            message="Enabled chunks do not have valid embeddings for the active configuration.",
        )


def _response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=dict(details) if details is not None else None,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, error: AppError) -> JSONResponse:
        return _response(
            status_code=error.status_code,
            code=error.code,
            message=error.message,
            details=error.details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        if error.status_code == 404:
            return _response(
                status_code=404,
                code="not_found",
                message="Resource not found.",
            )
        return _response(
            status_code=error.status_code,
            code="http_error",
            message="Request could not be completed.",
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        _request: Request,
        _error: RequestValidationError,
    ) -> JSONResponse:
        # Pydantic validation details can include the rejected input. Authentication
        # endpoints must never reflect a submitted password back to the client.
        return _response(
            status_code=422,
            code="invalid_request",
            message="Request validation failed.",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, error: Exception) -> JSONResponse:
        logger.error(
            "Unhandled application error",
            extra={"error_type": type(error).__name__},
        )
        return _response(
            status_code=500,
            code="internal_server_error",
            message="An unexpected server error occurred.",
        )
