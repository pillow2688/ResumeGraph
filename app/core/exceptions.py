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
