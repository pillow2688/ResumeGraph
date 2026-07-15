from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from app.api.dependencies.admin_auth import get_current_admin
from app.core.exceptions import (
    DocumentVersionNotFoundResponseError,
    DocumentVersionNotProcessableResponseError,
    IngestionJobNotFoundResponseError,
    IngestionUnavailableResponseError,
)
from app.schemas.admin_auth import AdminPrincipal
from app.schemas.error import ErrorResponse
from app.schemas.ingestion import (
    DocumentChunkResponse,
    IngestionJobCreateResponse,
    IngestionJobDetail,
)
from app.services.ingestion import (
    DocumentVersionNotProcessableError,
    IngestionJobNotFoundError,
    IngestionService,
    IngestionUnavailableError,
    IngestionVersionNotFoundError,
)

router = APIRouter(tags=["admin-ingestion"])

INGESTION_ERROR_RESPONSES = {
    401: {"description": "Administrator authentication required", "model": ErrorResponse},
    503: {"description": "Document processing unavailable", "model": ErrorResponse},
}


def _service(request: Request) -> IngestionService:
    return cast(IngestionService, request.app.state.ingestion_service)


def _raise_service_error(error: Exception) -> None:
    if isinstance(error, IngestionVersionNotFoundError):
        raise DocumentVersionNotFoundResponseError from error
    if isinstance(error, IngestionJobNotFoundError):
        raise IngestionJobNotFoundResponseError from error
    if isinstance(error, DocumentVersionNotProcessableError):
        raise DocumentVersionNotProcessableResponseError from error
    if isinstance(error, IngestionUnavailableError):
        raise IngestionUnavailableResponseError from error
    raise error


@router.post(
    "/api/v1/admin/document-versions/{version_id}/process",
    response_model=IngestionJobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **INGESTION_ERROR_RESPONSES,
        404: {"description": "Document version not found", "model": ErrorResponse},
        409: {"description": "Document version not processable", "model": ErrorResponse},
    },
)
async def create_ingestion_job(
    version_id: UUID,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> IngestionJobCreateResponse:
    try:
        return await _service(request).create_job(version_id)
    except (
        IngestionVersionNotFoundError,
        DocumentVersionNotProcessableError,
        IngestionUnavailableError,
    ) as error:
        _raise_service_error(error)


@router.get(
    "/api/v1/admin/jobs/{job_id}",
    response_model=IngestionJobDetail,
    responses={
        **INGESTION_ERROR_RESPONSES,
        404: {"description": "Ingestion job not found", "model": ErrorResponse},
    },
)
async def get_ingestion_job(
    job_id: UUID,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> IngestionJobDetail:
    try:
        return await _service(request).get_job(job_id)
    except (IngestionJobNotFoundError, IngestionUnavailableError) as error:
        _raise_service_error(error)


@router.get(
    "/api/v1/admin/document-versions/{version_id}/chunks",
    response_model=list[DocumentChunkResponse],
    responses={
        **INGESTION_ERROR_RESPONSES,
        404: {"description": "Document version not found", "model": ErrorResponse},
    },
)
async def list_document_chunks(
    version_id: UUID,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> list[DocumentChunkResponse]:
    try:
        return await _service(request).list_chunks(version_id)
    except (IngestionVersionNotFoundError, IngestionUnavailableError) as error:
        _raise_service_error(error)
