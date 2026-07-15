import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.repositories.ingestion import (
    CreateIngestionJobResult,
    DocumentChunkRecord,
    DocumentVersionNotProcessableRepositoryError,
    IngestionJobRecord,
    IngestionRepositoryUnavailableError,
)
from app.services.ingestion import (
    DocumentVersionNotProcessableError,
    IngestionJobNotFoundError,
    IngestionService,
    IngestionUnavailableError,
    IngestionVersionNotFoundError,
    QueueUnavailableError,
)

NOW = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)


def make_job(*, status: str = "pending") -> IngestionJobRecord:
    return IngestionJobRecord(
        id=uuid4(),
        document_version_id=uuid4(),
        document_id=uuid4(),
        document_title="Architecture",
        version_number=2,
        status=status,
        stage="reading",
        progress=0,
        error_message=None,
        created_at=NOW,
        started_at=None,
        finished_at=None,
    )


class FakeRepository:
    def __init__(self, result: CreateIngestionJobResult | None) -> None:
        self.result = result
        self.job = result.record if result is not None else None
        self.chunks: list[DocumentChunkRecord] | None = []
        self.failure: Exception | None = None
        self.enqueue_failures: list[tuple[UUID, str]] = []

    def _check(self) -> None:
        if self.failure is not None:
            raise self.failure

    async def create_job(self, _version_id: UUID) -> CreateIngestionJobResult | None:
        self._check()
        return self.result

    async def mark_enqueue_failed(self, job_id: UUID, *, error_message: str) -> None:
        self._check()
        self.enqueue_failures.append((job_id, error_message))
        if self.job is not None:
            self.job = replace(
                self.job,
                status="failed",
                error_message=error_message,
                finished_at=NOW,
            )

    async def get_job(self, _job_id: UUID) -> IngestionJobRecord | None:
        self._check()
        return self.job

    async def list_chunks(self, _version_id: UUID) -> list[DocumentChunkRecord] | None:
        self._check()
        return self.chunks


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[UUID] = []
        self.unavailable = False

    async def enqueue(self, job_id: UUID) -> None:
        if self.unavailable:
            raise QueueUnavailableError
        self.enqueued.append(job_id)


def make_service(
    repository: FakeRepository,
    queue: FakeQueue,
    timeout: float = 1,
) -> IngestionService:
    return IngestionService(
        repository,
        queue,
        dependency_timeout_seconds=timeout,
    )


def test_create_job_persists_then_enqueues_and_returns_pending_response() -> None:
    job = make_job()
    repository = FakeRepository(CreateIngestionJobResult(record=job, created=True))
    queue = FakeQueue()

    response = asyncio.run(make_service(repository, queue).create_job(job.document_version_id))

    assert response.job_id == job.id
    assert response.status == "pending"
    assert queue.enqueued == [job.id]


def test_create_job_is_idempotent_while_a_job_is_active() -> None:
    job = make_job(status="processing")
    repository = FakeRepository(CreateIngestionJobResult(record=job, created=False))
    queue = FakeQueue()

    response = asyncio.run(make_service(repository, queue).create_job(job.document_version_id))

    assert response.job_id == job.id
    assert response.status == "processing"
    assert queue.enqueued == []


def test_retry_reenqueues_an_existing_pending_job_after_an_api_interruption() -> None:
    job = make_job(status="pending")
    repository = FakeRepository(CreateIngestionJobResult(record=job, created=False))
    queue = FakeQueue()

    response = asyncio.run(make_service(repository, queue).create_job(job.document_version_id))

    assert response.job_id == job.id
    assert response.status == "pending"
    assert queue.enqueued == [job.id]


def test_queue_failure_marks_postgresql_job_failed_and_returns_sanitized_error() -> None:
    job = make_job()
    repository = FakeRepository(CreateIngestionJobResult(record=job, created=True))
    queue = FakeQueue()
    queue.unavailable = True

    with pytest.raises(IngestionUnavailableError) as raised:
        asyncio.run(make_service(repository, queue).create_job(job.document_version_id))

    assert repository.enqueue_failures == [(job.id, "Document processing could not be queued.")]
    assert repository.job is not None and repository.job.status == "failed"
    assert "redis" not in str(raised.value).lower()


def test_create_job_maps_missing_and_already_processed_versions() -> None:
    queue = FakeQueue()
    with pytest.raises(IngestionVersionNotFoundError):
        asyncio.run(make_service(FakeRepository(None), queue).create_job(uuid4()))

    repository = FakeRepository(None)
    repository.failure = DocumentVersionNotProcessableRepositoryError()
    with pytest.raises(DocumentVersionNotProcessableError):
        asyncio.run(make_service(repository, queue).create_job(uuid4()))


def test_get_job_and_chunks_map_records_without_using_queue_state() -> None:
    job = make_job(status="completed")
    repository = FakeRepository(CreateIngestionJobResult(record=job, created=False))
    repository.job = replace(job, stage="saving", progress=100, finished_at=NOW)
    repository.chunks = [
        DocumentChunkRecord(
            id=uuid4(),
            document_version_id=job.document_version_id,
            chunk_index=0,
            heading_path=("Architecture",),
            content="## Architecture\n\nContent",
            content_hash="a" * 64,
            character_count=25,
            enabled=True,
            created_at=NOW,
        )
    ]
    queue = FakeQueue()

    detail = asyncio.run(make_service(repository, queue).get_job(job.id))
    chunks = asyncio.run(make_service(repository, queue).list_chunks(job.document_version_id))

    assert detail.document_title == "Architecture"
    assert detail.status == "completed"
    assert chunks[0].heading_path == ("Architecture",)
    assert chunks[0].chunk_index == 0
    assert queue.enqueued == []


def test_missing_job_and_version_use_specific_errors() -> None:
    repository = FakeRepository(None)
    repository.chunks = None
    queue = FakeQueue()

    with pytest.raises(IngestionJobNotFoundError):
        asyncio.run(make_service(repository, queue).get_job(uuid4()))
    with pytest.raises(IngestionVersionNotFoundError):
        asyncio.run(make_service(repository, queue).list_chunks(uuid4()))


def test_repository_failure_and_timeout_are_sanitized() -> None:
    repository = FakeRepository(None)
    repository.failure = IngestionRepositoryUnavailableError()
    service = make_service(repository, FakeQueue())

    with pytest.raises(IngestionUnavailableError) as raised:
        asyncio.run(service.get_job(uuid4()))
    assert "postgresql" not in str(raised.value).lower()

    class HangingRepository(FakeRepository):
        async def get_job(self, _job_id: UUID) -> IngestionJobRecord | None:
            await asyncio.Event().wait()
            return None

    with pytest.raises(IngestionUnavailableError):
        asyncio.run(make_service(HangingRepository(None), FakeQueue(), 0.01).get_job(uuid4()))
