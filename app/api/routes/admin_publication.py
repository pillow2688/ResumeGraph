from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.dependencies.admin_auth import get_current_admin
from app.core.exceptions import (
    DocumentChunkNotEditableResponseError,
    DocumentChunkNotFoundResponseError,
    DocumentNotFoundResponseError,
    DocumentVersionNotFoundResponseError,
    DocumentVersionNotPublishableResponseError,
    KnowledgePublicationUnavailableResponseError,
    PublicationIntegrityResponseError,
)
from app.schemas.admin_auth import AdminPrincipal
from app.schemas.error import ErrorResponse
from app.schemas.ingestion import DocumentChunkResponse
from app.schemas.publication import (
    DocumentChunkUpdateRequest,
    EmbeddingConfigResponse,
    PublicationState,
)
from app.services.publication import (
    ChunkNotEditableError,
    ChunkNotFoundError,
    DocumentNotFoundError,
    PublicationIntegrityError,
    PublicationService,
    PublicationUnavailableError,
    VersionNotFoundError,
    VersionNotPublishableError,
)

router = APIRouter(tags=["admin-publication"])

PUBLICATION_ERROR_RESPONSES = {
    401: {"description": "Administrator authentication required", "model": ErrorResponse},
    503: {"description": "Knowledge publication unavailable", "model": ErrorResponse},
}


def _service(request: Request) -> PublicationService:
    return cast(PublicationService, request.app.state.publication_service)


@router.get(
    "/api/v1/admin/embedding-config",
    response_model=EmbeddingConfigResponse,
    responses=PUBLICATION_ERROR_RESPONSES,
)
async def get_embedding_config(
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> EmbeddingConfigResponse:
    settings = request.app.state.settings
    return EmbeddingConfigResponse(
        provider_name=settings.embedding_provider_name,
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        send_dimensions=settings.embedding_send_dimensions,
        batch_size=settings.embedding_batch_size,
        timeout_seconds=settings.embedding_timeout_seconds,
        max_retries=settings.embedding_max_retries,
    )


@router.patch(
    "/api/v1/admin/document-chunks/{chunk_id}",
    response_model=DocumentChunkResponse,
    responses={
        **PUBLICATION_ERROR_RESPONSES,
        404: {"description": "Document chunk not found", "model": ErrorResponse},
        409: {"description": "Document chunk not editable", "model": ErrorResponse},
    },
)
async def update_document_chunk(
    chunk_id: UUID,
    payload: DocumentChunkUpdateRequest,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> DocumentChunkResponse:
    try:
        return await _service(request).set_chunk_enabled(chunk_id, enabled=payload.enabled)
    except ChunkNotFoundError as error:
        raise DocumentChunkNotFoundResponseError from error
    except ChunkNotEditableError as error:
        raise DocumentChunkNotEditableResponseError from error
    except PublicationUnavailableError as error:
        raise KnowledgePublicationUnavailableResponseError from error


@router.post(
    "/api/v1/admin/document-versions/{version_id}/publish",
    response_model=PublicationState,
    responses={
        **PUBLICATION_ERROR_RESPONSES,
        404: {"description": "Document version not found", "model": ErrorResponse},
        409: {"description": "Document version is not publishable", "model": ErrorResponse},
    },
)
async def publish_document_version(
    version_id: UUID,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> PublicationState:
    try:
        return await _service(request).publish_version(version_id)
    except VersionNotFoundError as error:
        raise DocumentVersionNotFoundResponseError from error
    except VersionNotPublishableError as error:
        raise DocumentVersionNotPublishableResponseError from error
    except PublicationIntegrityError as error:
        raise PublicationIntegrityResponseError from error
    except PublicationUnavailableError as error:
        raise KnowledgePublicationUnavailableResponseError from error


@router.delete(
    "/api/v1/admin/documents/{document_id}/publication",
    response_model=PublicationState,
    responses={
        **PUBLICATION_ERROR_RESPONSES,
        404: {"description": "Knowledge document not found", "model": ErrorResponse},
    },
)
async def unpublish_document(
    document_id: UUID,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> PublicationState:
    try:
        return await _service(request).unpublish_document(document_id)
    except DocumentNotFoundError as error:
        raise DocumentNotFoundResponseError from error
    except PublicationUnavailableError as error:
        raise KnowledgePublicationUnavailableResponseError from error
