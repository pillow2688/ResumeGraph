import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.repositories.indexing import IndexingVersionNotProcessableRepositoryError
from app.repositories.ingestion import CreateIngestionJobResult, IngestionJobRecord
from app.services.indexing import (
    IndexingService,
    IndexingUnavailableError,
    IndexingVersionNotProcessableError,
)
from app.services.ingestion import QueueUnavailableError

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def make_record(*, status: str = "pending") -> IngestionJobRecord:
    return IngestionJobRecord(
        id=uuid4(),
        document_version_id=uuid4(),
        document_id=uuid4(),
        document_title="Architecture",
        version_number=2,
        status=status,
        stage="rule_check",
        progress=0,
        error_message=None,
        created_at=NOW,
        started_at=None,
        finished_at=None,
        job_type="knowledge_indexing",
    )


class FakeRepository:
    def __init__(self, result=None) -> None:
        self.result = result
        self.failure: Exception | None = None
        self.enqueue_failures: list[tuple[object, str]] = []

    async def create_job(self, _version_id):
        if self.failure is not None:
            raise self.failure
        return self.result

    async def mark_enqueue_failed(self, job_id, *, error_message: str) -> None:
        self.enqueue_failures.append((job_id, error_message))


class FakeQueue:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.job_ids: list[object] = []

    async def enqueue_indexing(self, job_id) -> None:
        if self.fail:
            raise QueueUnavailableError
        self.job_ids.append(job_id)


def test_service_enqueues_new_or_pending_indexing_job_on_shared_queue() -> None:
    record = make_record()
    repository = FakeRepository(CreateIngestionJobResult(record=record, created=True))
    queue = FakeQueue()
    service = IndexingService(repository, queue, dependency_timeout_seconds=1)

    response = asyncio.run(service.create_job(record.document_version_id))

    assert response.job_id == record.id
    assert response.status == "pending"
    assert queue.job_ids == [record.id]


def test_service_translates_not_processable_and_sanitizes_queue_failure() -> None:
    repository = FakeRepository()
    repository.failure = IndexingVersionNotProcessableRepositoryError()
    service = IndexingService(repository, FakeQueue(), dependency_timeout_seconds=1)

    with pytest.raises(IndexingVersionNotProcessableError):
        asyncio.run(service.create_job(uuid4()))

    record = make_record()
    repository = FakeRepository(CreateIngestionJobResult(record=record, created=True))
    service = IndexingService(repository, FakeQueue(fail=True), dependency_timeout_seconds=1)

    with pytest.raises(IndexingUnavailableError) as raised:
        asyncio.run(service.create_job(record.document_version_id))

    assert repository.enqueue_failures == [(record.id, "Knowledge indexing could not be queued.")]
    assert "redis" not in str(raised.value).lower()
