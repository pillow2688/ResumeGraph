import asyncio
from collections.abc import Awaitable
from typing import Protocol
from uuid import UUID

from app.repositories.ingestion import (
    CreateIngestionJobResult,
    DocumentChunkRecord,
    DocumentVersionNotProcessableRepositoryError,
    IngestionJobRecord,
    IngestionRepositoryUnavailableError,
)
from app.schemas.ingestion import (
    DocumentChunkResponse,
    IngestionJobCreateResponse,
    IngestionJobDetail,
)


class QueueUnavailableError(Exception):
    pass


class IngestionVersionNotFoundError(Exception):
    pass


class IngestionJobNotFoundError(Exception):
    pass


class DocumentVersionNotProcessableError(Exception):
    pass


class IngestionUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Document processing is temporarily unavailable.")


class JobQueue(Protocol):
    async def enqueue(self, job_id: UUID) -> None: ...


class IngestionRepositoryBackend(Protocol):
    async def create_job(self, version_id: UUID) -> CreateIngestionJobResult | None: ...

    async def mark_enqueue_failed(self, job_id: UUID, *, error_message: str) -> None: ...

    async def get_job(self, job_id: UUID) -> IngestionJobRecord | None: ...

    async def list_chunks(self, version_id: UUID) -> list[DocumentChunkRecord] | None: ...


async def _await_repository[T](awaitable: Awaitable[T], timeout_seconds: float) -> T:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as error:
        raise IngestionUnavailableError from error


def _job_detail(record: IngestionJobRecord) -> IngestionJobDetail:
    return IngestionJobDetail(
        job_id=record.id,
        document_version_id=record.document_version_id,
        document_id=record.document_id,
        document_title=record.document_title,
        version_number=record.version_number,
        status=record.status,
        stage=record.stage,
        progress=record.progress,
        error_message=record.error_message,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def _chunk_response(record: DocumentChunkRecord) -> DocumentChunkResponse:
    return DocumentChunkResponse(**record.__dict__)


class IngestionService:
    def __init__(
        self,
        repository: IngestionRepositoryBackend,
        queue: JobQueue,
        *,
        dependency_timeout_seconds: float,
    ) -> None:
        self._repository = repository
        self._queue = queue
        self._dependency_timeout_seconds = dependency_timeout_seconds

    async def create_job(self, version_id: UUID) -> IngestionJobCreateResponse:
        try:
            result = await _await_repository(
                self._repository.create_job(version_id),
                self._dependency_timeout_seconds,
            )
        except DocumentVersionNotProcessableRepositoryError as error:
            raise DocumentVersionNotProcessableError from error
        except IngestionRepositoryUnavailableError as error:
            raise IngestionUnavailableError from error
        if result is None:
            raise IngestionVersionNotFoundError
        # Re-enqueue an existing pending record as well. This closes the small
        # PostgreSQL-commit/Redis-enqueue crash window without duplicating work
        # once a worker has advanced the job to processing.
        if result.created or result.record.status == "pending":
            try:
                await asyncio.wait_for(
                    self._queue.enqueue(result.record.id),
                    timeout=self._dependency_timeout_seconds,
                )
            except (QueueUnavailableError, TimeoutError) as error:
                try:
                    await _await_repository(
                        self._repository.mark_enqueue_failed(
                            result.record.id,
                            error_message="Document processing could not be queued.",
                        ),
                        self._dependency_timeout_seconds,
                    )
                except (
                    IngestionRepositoryUnavailableError,
                    IngestionUnavailableError,
                ):
                    pass
                raise IngestionUnavailableError from error
        return IngestionJobCreateResponse(
            job_id=result.record.id,
            status=result.record.status,
        )

    async def get_job(self, job_id: UUID) -> IngestionJobDetail:
        try:
            record = await _await_repository(
                self._repository.get_job(job_id),
                self._dependency_timeout_seconds,
            )
        except IngestionRepositoryUnavailableError as error:
            raise IngestionUnavailableError from error
        if record is None:
            raise IngestionJobNotFoundError
        return _job_detail(record)

    async def list_chunks(self, version_id: UUID) -> list[DocumentChunkResponse]:
        try:
            records = await _await_repository(
                self._repository.list_chunks(version_id),
                self._dependency_timeout_seconds,
            )
        except IngestionRepositoryUnavailableError as error:
            raise IngestionUnavailableError from error
        if records is None:
            raise IngestionVersionNotFoundError
        return [_chunk_response(record) for record in records]
