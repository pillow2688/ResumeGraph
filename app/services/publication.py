import asyncio
from collections.abc import Awaitable
from typing import Protocol
from uuid import UUID

from app.repositories.ingestion import DocumentChunkRecord
from app.repositories.publication import (
    ChunkNotEditableRepositoryError,
    PublicationIntegrityRepositoryError,
    PublicationRepositoryUnavailableError,
    PublicationStateRecord,
    VersionNotPublishableRepositoryError,
)
from app.schemas.ingestion import DocumentChunkResponse
from app.schemas.publication import PublicationState
from app.services.deduplication import DeduplicationUnavailableError


class ChunkNotFoundError(Exception):
    pass


class ChunkNotEditableError(Exception):
    pass


class VersionNotFoundError(Exception):
    pass


class DocumentNotFoundError(Exception):
    pass


class VersionNotPublishableError(Exception):
    pass


class PublicationIntegrityError(Exception):
    pass


class PublicationUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Knowledge publication is temporarily unavailable.")


class PublicationRepositoryBackend(Protocol):
    async def set_chunk_enabled(
        self,
        chunk_id: UUID,
        *,
        enabled: bool,
    ) -> DocumentChunkRecord | None: ...

    async def publish_version(
        self,
        version_id: UUID,
        *,
        provider_name: str,
        model_name: str,
        dimensions: int,
    ) -> PublicationStateRecord | None: ...

    async def unpublish_document(
        self,
        document_id: UUID,
    ) -> PublicationStateRecord | None: ...


class DeduplicationServiceBackend(Protocol):
    async def rebuild_profile_scope(self) -> object: ...

    async def rebuild_project_scope(self, project_id: UUID) -> object: ...


async def _await_repository[T](awaitable: Awaitable[T], timeout_seconds: float) -> T:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as error:
        raise PublicationUnavailableError from error


def _chunk_response(record: DocumentChunkRecord) -> DocumentChunkResponse:
    payload = record.__dict__.copy()
    if payload["extracted_metadata"] is None:
        payload["extracted_metadata"] = {}
    return DocumentChunkResponse(**payload)


class PublicationService:
    def __init__(
        self,
        repository: PublicationRepositoryBackend,
        *,
        provider_name: str,
        model_name: str,
        dimensions: int,
        dependency_timeout_seconds: float,
        deduplication_service: DeduplicationServiceBackend | None = None,
    ) -> None:
        self._repository = repository
        self._provider_name = provider_name
        self._model_name = model_name
        self._dimensions = dimensions
        self._dependency_timeout_seconds = dependency_timeout_seconds
        self._deduplication_service = deduplication_service

    async def set_chunk_enabled(
        self,
        chunk_id: UUID,
        *,
        enabled: bool,
    ) -> DocumentChunkResponse:
        try:
            record = await _await_repository(
                self._repository.set_chunk_enabled(chunk_id, enabled=enabled),
                self._dependency_timeout_seconds,
            )
        except ChunkNotEditableRepositoryError as error:
            raise ChunkNotEditableError from error
        except PublicationRepositoryUnavailableError as error:
            raise PublicationUnavailableError from error
        if record is None:
            raise ChunkNotFoundError
        return _chunk_response(record)

    async def publish_version(self, version_id: UUID) -> PublicationState:
        try:
            record = await _await_repository(
                self._repository.publish_version(
                    version_id,
                    provider_name=self._provider_name,
                    model_name=self._model_name,
                    dimensions=self._dimensions,
                ),
                self._dependency_timeout_seconds,
            )
        except VersionNotPublishableRepositoryError as error:
            raise VersionNotPublishableError from error
        except PublicationIntegrityRepositoryError as error:
            raise PublicationIntegrityError from error
        except PublicationRepositoryUnavailableError as error:
            raise PublicationUnavailableError from error
        if record is None:
            raise VersionNotFoundError
        await self._rebuild_scope(record)
        return PublicationState(**record.__dict__)

    async def unpublish_document(self, document_id: UUID) -> PublicationState:
        try:
            record = await _await_repository(
                self._repository.unpublish_document(document_id),
                self._dependency_timeout_seconds,
            )
        except PublicationRepositoryUnavailableError as error:
            raise PublicationUnavailableError from error
        if record is None:
            raise DocumentNotFoundError
        await self._rebuild_scope(record)
        return PublicationState(**record.__dict__)

    async def _rebuild_scope(self, record: PublicationStateRecord) -> None:
        if self._deduplication_service is None:
            return
        try:
            if record.document_scope == "profile":
                await _await_repository(
                    self._deduplication_service.rebuild_profile_scope(),
                    self._dependency_timeout_seconds,
                )
            elif record.project_id is not None:
                await _await_repository(
                    self._deduplication_service.rebuild_project_scope(record.project_id),
                    self._dependency_timeout_seconds,
                )
            else:
                raise PublicationUnavailableError
        except DeduplicationUnavailableError as error:
            raise PublicationUnavailableError from error
