import asyncio
from typing import Protocol
from uuid import UUID

from app.repositories.indexing import (
    IndexingRepositoryUnavailableError,
    IndexingVersionNotProcessableRepositoryError,
)
from app.repositories.ingestion import CreateIngestionJobResult
from app.schemas.ingestion import IngestionJobCreateResponse
from app.services.ingestion import QueueUnavailableError


class IndexingVersionNotFoundError(Exception):
    pass


class IndexingVersionNotProcessableError(Exception):
    pass


class IndexingUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Knowledge indexing is temporarily unavailable.")


class IndexingRepositoryBackend(Protocol):
    async def create_job(self, version_id: UUID) -> CreateIngestionJobResult | None: ...

    async def mark_enqueue_failed(self, job_id: UUID, *, error_message: str) -> None: ...


class IndexingJobQueue(Protocol):
    async def enqueue_indexing(self, job_id: UUID) -> None: ...


class IndexingService:
    def __init__(
        self,
        repository: IndexingRepositoryBackend,
        queue: IndexingJobQueue,
        *,
        dependency_timeout_seconds: float,
    ) -> None:
        self._repository = repository
        self._queue = queue
        self._dependency_timeout_seconds = dependency_timeout_seconds

    async def create_job(self, version_id: UUID) -> IngestionJobCreateResponse:
        try:
            result = await asyncio.wait_for(
                self._repository.create_job(version_id),
                timeout=self._dependency_timeout_seconds,
            )
        except IndexingVersionNotProcessableRepositoryError as error:
            raise IndexingVersionNotProcessableError from error
        except (IndexingRepositoryUnavailableError, TimeoutError) as error:
            raise IndexingUnavailableError from error
        if result is None:
            raise IndexingVersionNotFoundError

        if result.created or result.record.status == "pending":
            try:
                await asyncio.wait_for(
                    self._queue.enqueue_indexing(result.record.id),
                    timeout=self._dependency_timeout_seconds,
                )
            except (QueueUnavailableError, TimeoutError) as error:
                try:
                    await asyncio.wait_for(
                        self._repository.mark_enqueue_failed(
                            result.record.id,
                            error_message="Knowledge indexing could not be queued.",
                        ),
                        timeout=self._dependency_timeout_seconds,
                    )
                except (IndexingRepositoryUnavailableError, TimeoutError):
                    pass
                raise IndexingUnavailableError from error

        return IngestionJobCreateResponse(
            job_id=result.record.id,
            status=result.record.status,
        )
