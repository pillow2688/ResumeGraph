import asyncio
from collections.abc import Awaitable
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Protocol
from uuid import UUID

from app.repositories.knowledge_document import (
    DocumentVersionRecord,
    DuplicateDocumentVersionRepositoryError,
    KnowledgeDocumentRecord,
    KnowledgeDocumentRepositoryUnavailableError,
)
from app.schemas.knowledge_document import (
    DocumentProjectSummary,
    DocumentVersion,
    DocumentVersionSummary,
    KnowledgeDocumentDetail,
    KnowledgeDocumentSummary,
)


class KnowledgeDocumentRepositoryBackend(Protocol):
    async def create_document(
        self,
        *,
        project_id: UUID,
        title: str,
        source_type: str,
        original_filename: str | None,
        raw_content: str,
        content_hash: str,
    ) -> KnowledgeDocumentRecord | None: ...

    async def list_documents(self, project_id: UUID) -> list[KnowledgeDocumentRecord] | None: ...

    async def get_document(self, document_id: UUID) -> KnowledgeDocumentRecord | None: ...

    async def update_document_title(
        self, document_id: UUID, *, title: str
    ) -> KnowledgeDocumentRecord | None: ...

    async def create_version(
        self,
        document_id: UUID,
        *,
        source_type: str,
        original_filename: str | None,
        raw_content: str,
        content_hash: str,
    ) -> DocumentVersionRecord | None: ...

    async def list_versions(self, document_id: UUID) -> list[DocumentVersionRecord] | None: ...

    async def get_version(self, version_id: UUID) -> DocumentVersionRecord | None: ...


class InvalidDocumentRequestError(Exception):
    pass


class ProjectNotFoundError(Exception):
    pass


class DocumentNotFoundError(Exception):
    pass


class DocumentVersionNotFoundError(Exception):
    pass


class DuplicateDocumentVersionError(Exception):
    pass


class UnsupportedMarkdownFileError(Exception):
    pass


class MarkdownTooLargeError(Exception):
    pass


class InvalidMarkdownEncodingError(Exception):
    pass


class InvalidMarkdownContentError(Exception):
    pass


class KnowledgeDocumentUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Knowledge document management is temporarily unavailable.")


async def _await_dependency[T](awaitable: Awaitable[T], timeout_seconds: float) -> T:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as error:
        raise KnowledgeDocumentUnavailableError from error


def _normalize_title(title: str) -> str:
    normalized = title.strip()
    if not normalized or len(normalized) > 200:
        raise InvalidDocumentRequestError
    return normalized


def _safe_markdown_filename(filename: str) -> str:
    basename = PurePosixPath(filename.replace("\\", "/")).name.strip()
    if (
        not basename
        or len(basename) > 255
        or PurePosixPath(basename).suffix.lower() != ".md"
        or any(ord(character) < 32 for character in basename)
    ):
        raise UnsupportedMarkdownFileError
    return basename


def _validate_text_content(content: str, *, max_bytes: int) -> tuple[str, str]:
    normalized = content.removeprefix("\ufeff")
    try:
        encoded = normalized.encode("utf-8")
    except UnicodeEncodeError as error:
        raise InvalidMarkdownEncodingError from error
    if len(encoded) > max_bytes:
        raise MarkdownTooLargeError
    if not normalized.strip() or "\x00" in normalized:
        raise InvalidMarkdownContentError
    return normalized, sha256(encoded).hexdigest()


def _decode_upload(content: bytes, *, max_bytes: int) -> str:
    if len(content) > max_bytes:
        raise MarkdownTooLargeError
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise InvalidMarkdownEncodingError from error


def _to_version_summary(record: DocumentVersionRecord) -> DocumentVersionSummary:
    return DocumentVersionSummary(
        id=record.id,
        document_id=record.document_id,
        version_number=record.version_number,
        source_type=record.source_type,
        original_filename=record.original_filename,
        status=record.status,
        created_at=record.created_at,
        content_size_bytes=record.content_size_bytes,
    )


def _to_version(record: DocumentVersionRecord) -> DocumentVersion:
    if record.raw_content is None:
        raise KnowledgeDocumentUnavailableError
    return DocumentVersion(
        id=record.id,
        document_id=record.document_id,
        version_number=record.version_number,
        source_type=record.source_type,
        original_filename=record.original_filename,
        raw_content=record.raw_content,
        status=record.status,
        created_at=record.created_at,
        content_size_bytes=record.content_size_bytes,
    )


def _to_summary(record: KnowledgeDocumentRecord) -> KnowledgeDocumentSummary:
    return KnowledgeDocumentSummary(
        id=record.id,
        project_id=record.project_id,
        title=record.title,
        created_at=record.created_at,
        updated_at=record.updated_at,
        version_count=record.version_count,
        current_published_version_id=record.current_published_version_id,
        latest_version=(
            _to_version_summary(record.latest_version)
            if record.latest_version is not None
            else None
        ),
    )


def _to_detail(record: KnowledgeDocumentRecord) -> KnowledgeDocumentDetail:
    summary = _to_summary(record)
    return KnowledgeDocumentDetail(
        **summary.model_dump(),
        project=DocumentProjectSummary(id=record.project_id, name=record.project_name),
    )


class KnowledgeDocumentService:
    def __init__(
        self,
        repository: KnowledgeDocumentRepositoryBackend,
        *,
        markdown_max_bytes: int,
        dependency_timeout_seconds: float,
    ) -> None:
        self._repository = repository
        self._markdown_max_bytes = markdown_max_bytes
        self._dependency_timeout_seconds = dependency_timeout_seconds

    async def create_document_from_paste(
        self,
        project_id: UUID,
        *,
        title: str,
        content: str,
    ) -> KnowledgeDocumentDetail:
        normalized_title = _normalize_title(title)
        raw_content, content_hash = _validate_text_content(
            content,
            max_bytes=self._markdown_max_bytes,
        )
        return await self._create_document(
            project_id,
            title=normalized_title,
            source_type="pasted_markdown",
            original_filename=None,
            raw_content=raw_content,
            content_hash=content_hash,
        )

    async def create_document_from_upload(
        self,
        project_id: UUID,
        *,
        title: str,
        filename: str,
        content: bytes,
    ) -> KnowledgeDocumentDetail:
        normalized_title = _normalize_title(title)
        safe_filename = _safe_markdown_filename(filename)
        decoded = _decode_upload(content, max_bytes=self._markdown_max_bytes)
        raw_content, content_hash = _validate_text_content(
            decoded,
            max_bytes=self._markdown_max_bytes,
        )
        return await self._create_document(
            project_id,
            title=normalized_title,
            source_type="markdown_file",
            original_filename=safe_filename,
            raw_content=raw_content,
            content_hash=content_hash,
        )

    async def list_documents(self, project_id: UUID) -> list[KnowledgeDocumentSummary]:
        try:
            records = await _await_dependency(
                self._repository.list_documents(project_id),
                self._dependency_timeout_seconds,
            )
        except KnowledgeDocumentRepositoryUnavailableError as error:
            raise KnowledgeDocumentUnavailableError from error
        if records is None:
            raise ProjectNotFoundError
        return [_to_summary(record) for record in records]

    async def get_document(self, document_id: UUID) -> KnowledgeDocumentDetail:
        record = await self._load_document(document_id)
        if record is None:
            raise DocumentNotFoundError
        return _to_detail(record)

    async def update_document_title(
        self,
        document_id: UUID,
        *,
        title: str,
    ) -> KnowledgeDocumentDetail:
        normalized_title = _normalize_title(title)
        try:
            record = await _await_dependency(
                self._repository.update_document_title(document_id, title=normalized_title),
                self._dependency_timeout_seconds,
            )
        except KnowledgeDocumentRepositoryUnavailableError as error:
            raise KnowledgeDocumentUnavailableError from error
        if record is None:
            raise DocumentNotFoundError
        return _to_detail(record)

    async def create_version_from_paste(
        self,
        document_id: UUID,
        *,
        content: str,
    ) -> DocumentVersion:
        raw_content, content_hash = _validate_text_content(
            content,
            max_bytes=self._markdown_max_bytes,
        )
        return await self._create_version(
            document_id,
            source_type="pasted_markdown",
            original_filename=None,
            raw_content=raw_content,
            content_hash=content_hash,
        )

    async def create_version_from_upload(
        self,
        document_id: UUID,
        *,
        filename: str,
        content: bytes,
    ) -> DocumentVersion:
        safe_filename = _safe_markdown_filename(filename)
        decoded = _decode_upload(content, max_bytes=self._markdown_max_bytes)
        raw_content, content_hash = _validate_text_content(
            decoded,
            max_bytes=self._markdown_max_bytes,
        )
        return await self._create_version(
            document_id,
            source_type="markdown_file",
            original_filename=safe_filename,
            raw_content=raw_content,
            content_hash=content_hash,
        )

    async def list_versions(self, document_id: UUID) -> list[DocumentVersionSummary]:
        try:
            records = await _await_dependency(
                self._repository.list_versions(document_id),
                self._dependency_timeout_seconds,
            )
        except KnowledgeDocumentRepositoryUnavailableError as error:
            raise KnowledgeDocumentUnavailableError from error
        if records is None:
            raise DocumentNotFoundError
        return [_to_version_summary(record) for record in records]

    async def get_version(self, version_id: UUID) -> DocumentVersion:
        try:
            record = await _await_dependency(
                self._repository.get_version(version_id),
                self._dependency_timeout_seconds,
            )
        except KnowledgeDocumentRepositoryUnavailableError as error:
            raise KnowledgeDocumentUnavailableError from error
        if record is None:
            raise DocumentVersionNotFoundError
        return _to_version(record)

    async def _create_document(
        self,
        project_id: UUID,
        *,
        title: str,
        source_type: str,
        original_filename: str | None,
        raw_content: str,
        content_hash: str,
    ) -> KnowledgeDocumentDetail:
        try:
            record = await _await_dependency(
                self._repository.create_document(
                    project_id=project_id,
                    title=title,
                    source_type=source_type,
                    original_filename=original_filename,
                    raw_content=raw_content,
                    content_hash=content_hash,
                ),
                self._dependency_timeout_seconds,
            )
        except KnowledgeDocumentRepositoryUnavailableError as error:
            raise KnowledgeDocumentUnavailableError from error
        if record is None:
            raise ProjectNotFoundError
        return _to_detail(record)

    async def _create_version(
        self,
        document_id: UUID,
        *,
        source_type: str,
        original_filename: str | None,
        raw_content: str,
        content_hash: str,
    ) -> DocumentVersion:
        try:
            record = await _await_dependency(
                self._repository.create_version(
                    document_id,
                    source_type=source_type,
                    original_filename=original_filename,
                    raw_content=raw_content,
                    content_hash=content_hash,
                ),
                self._dependency_timeout_seconds,
            )
        except DuplicateDocumentVersionRepositoryError as error:
            raise DuplicateDocumentVersionError from error
        except KnowledgeDocumentRepositoryUnavailableError as error:
            raise KnowledgeDocumentUnavailableError from error
        if record is None:
            raise DocumentNotFoundError
        return _to_version(record)

    async def _load_document(self, document_id: UUID) -> KnowledgeDocumentRecord | None:
        try:
            return await _await_dependency(
                self._repository.get_document(document_id),
                self._dependency_timeout_seconds,
            )
        except KnowledgeDocumentRepositoryUnavailableError as error:
            raise KnowledgeDocumentUnavailableError from error
