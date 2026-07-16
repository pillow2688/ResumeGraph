from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status

from app.api.dependencies.admin_auth import get_current_admin
from app.core.exceptions import (
    ActiveDocumentJobResponseError,
    DocumentConfirmationMismatchResponseError,
    DocumentNotFoundResponseError,
    DocumentVersionNotDeletableResponseError,
    DocumentVersionNotFoundResponseError,
    DuplicateDocumentVersionResponseError,
    InvalidDocumentRequestResponseError,
    InvalidMarkdownContentResponseError,
    InvalidMarkdownEncodingResponseError,
    KnowledgeDocumentUnavailableResponseError,
    MarkdownTooLargeResponseError,
    ProjectNotFoundResponseError,
    UnsupportedMarkdownFileResponseError,
)
from app.schemas.admin_auth import AdminPrincipal
from app.schemas.error import ErrorResponse
from app.schemas.knowledge_document import (
    DocumentVersion,
    DocumentVersionCreateRequest,
    DocumentVersionSummary,
    KnowledgeDocumentCreateRequest,
    KnowledgeDocumentDeleteRequest,
    KnowledgeDocumentDetail,
    KnowledgeDocumentSummary,
    KnowledgeDocumentUpdateRequest,
    TechnicalKnowledgeDocumentCreateRequest,
)
from app.services.knowledge_document import (
    DocumentNotFoundError,
    DocumentVersionNotFoundError,
    DuplicateDocumentVersionError,
    InvalidDocumentRequestError,
    InvalidMarkdownContentError,
    InvalidMarkdownEncodingError,
    KnowledgeDocumentService,
    KnowledgeDocumentUnavailableError,
    MarkdownTooLargeError,
    ProjectNotFoundError,
    UnsupportedMarkdownFileError,
)
from app.services.knowledge_lifecycle import (
    ActiveDocumentJobError,
    DocumentConfirmationError,
    KnowledgeLifecycleService,
    KnowledgeLifecycleUnavailableError,
    VersionNotDeletableError,
)
from app.services.knowledge_lifecycle import (
    KnowledgeDocumentNotFoundError as LifecycleDocumentNotFoundError,
)
from app.services.knowledge_lifecycle import (
    VersionNotFoundError as LifecycleVersionNotFoundError,
)

router = APIRouter(tags=["admin-documents"])

DOCUMENT_ERROR_RESPONSES = {
    401: {"description": "Administrator authentication required", "model": ErrorResponse},
    413: {"description": "Markdown content too large", "model": ErrorResponse},
    415: {"description": "Unsupported Markdown file", "model": ErrorResponse},
    422: {"description": "Invalid document or Markdown content", "model": ErrorResponse},
    503: {"description": "Document persistence unavailable", "model": ErrorResponse},
}


def _service(request: Request) -> KnowledgeDocumentService:
    return cast(KnowledgeDocumentService, request.app.state.knowledge_document_service)


def _lifecycle_service(request: Request) -> KnowledgeLifecycleService:
    return cast(KnowledgeLifecycleService, request.app.state.knowledge_lifecycle_service)


async def _read_upload(request: Request, file: UploadFile) -> bytes:
    limit = request.app.state.settings.markdown_max_bytes
    try:
        content = await file.read(limit + 1)
    finally:
        await file.close()
    if len(content) > limit:
        raise MarkdownTooLargeResponseError
    return content


def _raise_service_error(error: Exception) -> None:
    if isinstance(error, InvalidDocumentRequestError):
        raise InvalidDocumentRequestResponseError from error
    if isinstance(error, ProjectNotFoundError):
        raise ProjectNotFoundResponseError from error
    if isinstance(error, DocumentNotFoundError):
        raise DocumentNotFoundResponseError from error
    if isinstance(error, DocumentVersionNotFoundError):
        raise DocumentVersionNotFoundResponseError from error
    if isinstance(error, DuplicateDocumentVersionError):
        raise DuplicateDocumentVersionResponseError from error
    if isinstance(error, UnsupportedMarkdownFileError):
        raise UnsupportedMarkdownFileResponseError from error
    if isinstance(error, MarkdownTooLargeError):
        raise MarkdownTooLargeResponseError from error
    if isinstance(error, InvalidMarkdownEncodingError):
        raise InvalidMarkdownEncodingResponseError from error
    if isinstance(error, InvalidMarkdownContentError):
        raise InvalidMarkdownContentResponseError from error
    if isinstance(error, KnowledgeDocumentUnavailableError):
        raise KnowledgeDocumentUnavailableResponseError from error
    raise error


@router.post(
    "/api/v1/admin/profile-documents",
    response_model=KnowledgeDocumentDetail,
    status_code=status.HTTP_201_CREATED,
    responses=DOCUMENT_ERROR_RESPONSES,
)
async def create_pasted_profile_document(
    payload: KnowledgeDocumentCreateRequest,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> KnowledgeDocumentDetail:
    try:
        return await _service(request).create_profile_document_from_paste(
            title=payload.title,
            content=payload.content,
        )
    except (
        InvalidDocumentRequestError,
        MarkdownTooLargeError,
        InvalidMarkdownEncodingError,
        InvalidMarkdownContentError,
        KnowledgeDocumentUnavailableError,
    ) as error:
        _raise_service_error(error)


@router.post(
    "/api/v1/admin/profile-documents/upload",
    response_model=KnowledgeDocumentDetail,
    status_code=status.HTTP_201_CREATED,
    responses=DOCUMENT_ERROR_RESPONSES,
)
async def create_uploaded_profile_document(
    request: Request,
    title: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> KnowledgeDocumentDetail:
    content = await _read_upload(request, file)
    try:
        return await _service(request).create_profile_document_from_upload(
            title=title,
            filename=file.filename or "",
            content=content,
        )
    except (
        InvalidDocumentRequestError,
        UnsupportedMarkdownFileError,
        MarkdownTooLargeError,
        InvalidMarkdownEncodingError,
        InvalidMarkdownContentError,
        KnowledgeDocumentUnavailableError,
    ) as error:
        _raise_service_error(error)


@router.get(
    "/api/v1/admin/profile-documents",
    response_model=list[KnowledgeDocumentSummary],
    responses=DOCUMENT_ERROR_RESPONSES,
)
async def list_profile_documents(
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> list[KnowledgeDocumentSummary]:
    try:
        return await _service(request).list_profile_documents()
    except KnowledgeDocumentUnavailableError as error:
        _raise_service_error(error)


@router.post(
    "/api/v1/admin/technical-documents",
    response_model=KnowledgeDocumentDetail,
    status_code=status.HTTP_201_CREATED,
    responses=DOCUMENT_ERROR_RESPONSES,
)
async def create_pasted_technical_document(
    payload: TechnicalKnowledgeDocumentCreateRequest,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> KnowledgeDocumentDetail:
    try:
        return await _service(request).create_technical_document_from_paste(
            title=payload.title,
            content=payload.content,
        )
    except (
        InvalidDocumentRequestError,
        MarkdownTooLargeError,
        InvalidMarkdownEncodingError,
        InvalidMarkdownContentError,
        KnowledgeDocumentUnavailableError,
    ) as error:
        _raise_service_error(error)


@router.post(
    "/api/v1/admin/technical-documents/upload",
    response_model=KnowledgeDocumentDetail,
    status_code=status.HTTP_201_CREATED,
    responses=DOCUMENT_ERROR_RESPONSES,
)
async def create_uploaded_technical_document(
    request: Request,
    title: Annotated[str, Form()],
    knowledge_status: Annotated[Literal["general_knowledge"], Form()],
    file: Annotated[UploadFile, File()],
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> KnowledgeDocumentDetail:
    del knowledge_status
    content = await _read_upload(request, file)
    try:
        return await _service(request).create_technical_document_from_upload(
            title=title,
            filename=file.filename or "",
            content=content,
        )
    except (
        InvalidDocumentRequestError,
        UnsupportedMarkdownFileError,
        MarkdownTooLargeError,
        InvalidMarkdownEncodingError,
        InvalidMarkdownContentError,
        KnowledgeDocumentUnavailableError,
    ) as error:
        _raise_service_error(error)


@router.get(
    "/api/v1/admin/technical-documents",
    response_model=list[KnowledgeDocumentSummary],
    responses=DOCUMENT_ERROR_RESPONSES,
)
async def list_technical_documents(
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> list[KnowledgeDocumentSummary]:
    try:
        return await _service(request).list_technical_documents()
    except KnowledgeDocumentUnavailableError as error:
        _raise_service_error(error)


@router.post(
    "/api/v1/admin/projects/{project_id}/documents",
    response_model=KnowledgeDocumentDetail,
    status_code=status.HTTP_201_CREATED,
    responses={
        **DOCUMENT_ERROR_RESPONSES,
        404: {"description": "Project not found", "model": ErrorResponse},
    },
)
async def create_pasted_document(
    project_id: UUID,
    payload: KnowledgeDocumentCreateRequest,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> KnowledgeDocumentDetail:
    try:
        return await _service(request).create_document_from_paste(
            project_id,
            title=payload.title,
            content=payload.content,
            knowledge_status=payload.knowledge_status,
        )
    except (
        InvalidDocumentRequestError,
        ProjectNotFoundError,
        MarkdownTooLargeError,
        InvalidMarkdownEncodingError,
        InvalidMarkdownContentError,
        KnowledgeDocumentUnavailableError,
    ) as error:
        _raise_service_error(error)


@router.post(
    "/api/v1/admin/projects/{project_id}/documents/upload",
    response_model=KnowledgeDocumentDetail,
    status_code=status.HTTP_201_CREATED,
    responses={
        **DOCUMENT_ERROR_RESPONSES,
        404: {"description": "Project not found", "model": ErrorResponse},
    },
)
async def create_uploaded_document(
    project_id: UUID,
    request: Request,
    title: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
    knowledge_status: Annotated[Literal["implemented", "planned"], Form()] = "implemented",
) -> KnowledgeDocumentDetail:
    content = await _read_upload(request, file)
    try:
        return await _service(request).create_document_from_upload(
            project_id,
            title=title,
            filename=file.filename or "",
            content=content,
            knowledge_status=knowledge_status,
        )
    except (
        InvalidDocumentRequestError,
        ProjectNotFoundError,
        UnsupportedMarkdownFileError,
        MarkdownTooLargeError,
        InvalidMarkdownEncodingError,
        InvalidMarkdownContentError,
        KnowledgeDocumentUnavailableError,
    ) as error:
        _raise_service_error(error)


@router.get(
    "/api/v1/admin/projects/{project_id}/documents",
    response_model=list[KnowledgeDocumentSummary],
    responses={
        **DOCUMENT_ERROR_RESPONSES,
        404: {"description": "Project not found", "model": ErrorResponse},
    },
)
async def list_project_documents(
    project_id: UUID,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> list[KnowledgeDocumentSummary]:
    try:
        return await _service(request).list_documents(project_id)
    except (ProjectNotFoundError, KnowledgeDocumentUnavailableError) as error:
        _raise_service_error(error)


@router.get(
    "/api/v1/admin/documents/{document_id}",
    response_model=KnowledgeDocumentDetail,
    responses={
        **DOCUMENT_ERROR_RESPONSES,
        404: {"description": "Document not found", "model": ErrorResponse},
    },
)
async def get_document(
    document_id: UUID,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> KnowledgeDocumentDetail:
    try:
        return await _service(request).get_document(document_id)
    except (DocumentNotFoundError, KnowledgeDocumentUnavailableError) as error:
        _raise_service_error(error)


@router.patch(
    "/api/v1/admin/documents/{document_id}",
    response_model=KnowledgeDocumentDetail,
    responses={
        **DOCUMENT_ERROR_RESPONSES,
        404: {"description": "Document not found", "model": ErrorResponse},
    },
)
async def update_document_title(
    document_id: UUID,
    payload: KnowledgeDocumentUpdateRequest,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> KnowledgeDocumentDetail:
    try:
        return await _service(request).update_document_title(document_id, title=payload.title)
    except (
        InvalidDocumentRequestError,
        DocumentNotFoundError,
        KnowledgeDocumentUnavailableError,
    ) as error:
        _raise_service_error(error)


@router.post(
    "/api/v1/admin/documents/{document_id}/versions",
    response_model=DocumentVersion,
    status_code=status.HTTP_201_CREATED,
    responses={
        **DOCUMENT_ERROR_RESPONSES,
        404: {"description": "Document not found", "model": ErrorResponse},
        409: {"description": "Duplicate document version", "model": ErrorResponse},
    },
)
async def create_pasted_version(
    document_id: UUID,
    payload: DocumentVersionCreateRequest,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> DocumentVersion:
    try:
        return await _service(request).create_version_from_paste(
            document_id,
            content=payload.content,
        )
    except (
        DocumentNotFoundError,
        DuplicateDocumentVersionError,
        MarkdownTooLargeError,
        InvalidMarkdownEncodingError,
        InvalidMarkdownContentError,
        KnowledgeDocumentUnavailableError,
    ) as error:
        _raise_service_error(error)


@router.post(
    "/api/v1/admin/documents/{document_id}/versions/upload",
    response_model=DocumentVersion,
    status_code=status.HTTP_201_CREATED,
    responses={
        **DOCUMENT_ERROR_RESPONSES,
        404: {"description": "Document not found", "model": ErrorResponse},
        409: {"description": "Duplicate document version", "model": ErrorResponse},
    },
)
async def create_uploaded_version(
    document_id: UUID,
    request: Request,
    file: Annotated[UploadFile, File()],
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> DocumentVersion:
    content = await _read_upload(request, file)
    try:
        return await _service(request).create_version_from_upload(
            document_id,
            filename=file.filename or "",
            content=content,
        )
    except (
        DocumentNotFoundError,
        DuplicateDocumentVersionError,
        UnsupportedMarkdownFileError,
        MarkdownTooLargeError,
        InvalidMarkdownEncodingError,
        InvalidMarkdownContentError,
        KnowledgeDocumentUnavailableError,
    ) as error:
        _raise_service_error(error)


@router.get(
    "/api/v1/admin/documents/{document_id}/versions",
    response_model=list[DocumentVersionSummary],
    responses={
        **DOCUMENT_ERROR_RESPONSES,
        404: {"description": "Document not found", "model": ErrorResponse},
    },
)
async def list_document_versions(
    document_id: UUID,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> list[DocumentVersionSummary]:
    try:
        return await _service(request).list_versions(document_id)
    except (DocumentNotFoundError, KnowledgeDocumentUnavailableError) as error:
        _raise_service_error(error)


@router.get(
    "/api/v1/admin/document-versions/{version_id}",
    response_model=DocumentVersion,
    responses={
        **DOCUMENT_ERROR_RESPONSES,
        404: {"description": "Document version not found", "model": ErrorResponse},
    },
)
async def get_document_version(
    version_id: UUID,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> DocumentVersion:
    try:
        return await _service(request).get_version(version_id)
    except (DocumentVersionNotFoundError, KnowledgeDocumentUnavailableError) as error:
        _raise_service_error(error)


@router.delete(
    "/api/v1/admin/document-versions/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={
        401: {"description": "Administrator authentication required", "model": ErrorResponse},
        404: {"description": "Document version not found", "model": ErrorResponse},
        409: {"description": "Document version deletion is unsafe", "model": ErrorResponse},
        503: {"description": "Knowledge lifecycle unavailable", "model": ErrorResponse},
    },
)
async def delete_document_version(
    version_id: UUID,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> Response:
    try:
        await _lifecycle_service(request).delete_version(version_id)
    except LifecycleVersionNotFoundError as error:
        raise DocumentVersionNotFoundResponseError from error
    except VersionNotDeletableError as error:
        raise DocumentVersionNotDeletableResponseError from error
    except ActiveDocumentJobError as error:
        raise ActiveDocumentJobResponseError from error
    except KnowledgeLifecycleUnavailableError as error:
        raise KnowledgeDocumentUnavailableResponseError from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/api/v1/admin/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={
        401: {"description": "Administrator authentication required", "model": ErrorResponse},
        404: {"description": "Knowledge document not found", "model": ErrorResponse},
        409: {"description": "Permanent deletion is unsafe", "model": ErrorResponse},
        503: {"description": "Knowledge lifecycle unavailable", "model": ErrorResponse},
    },
)
async def permanently_delete_document(
    document_id: UUID,
    payload: KnowledgeDocumentDeleteRequest,
    request: Request,
    _current_admin: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> Response:
    try:
        await _lifecycle_service(request).delete_document(
            document_id,
            confirmation=payload.confirmation_title,
        )
    except LifecycleDocumentNotFoundError as error:
        raise DocumentNotFoundResponseError from error
    except DocumentConfirmationError as error:
        raise DocumentConfirmationMismatchResponseError from error
    except ActiveDocumentJobError as error:
        raise ActiveDocumentJobResponseError from error
    except KnowledgeLifecycleUnavailableError as error:
        raise KnowledgeDocumentUnavailableResponseError from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
