import asyncio
from hashlib import sha256
from uuid import UUID, uuid4

import pytest

from app.repositories.ingestion import ChunkToSave, IngestionWorkItem
from app.services.ingestion_worker import (
    DocumentProcessingFailedError,
    IngestionWorker,
)


class FakeWorkerRepository:
    def __init__(self, raw_content: str | None) -> None:
        self.job_id = uuid4()
        self.version_id = uuid4()
        self.raw_content = raw_content
        self.stages: list[tuple[str, int]] = []
        self.completed_chunks: list[ChunkToSave] | None = None
        self.failures: list[str] = []

    async def begin_job(self, job_id: UUID) -> IngestionWorkItem | None:
        assert job_id == self.job_id
        if self.raw_content is None:
            return None
        self.stages.append(("reading", 5))
        return IngestionWorkItem(
            job_id=self.job_id,
            document_version_id=self.version_id,
            raw_content=self.raw_content,
        )

    async def set_stage(self, job_id: UUID, *, stage: str, progress: int) -> bool:
        assert job_id == self.job_id
        self.stages.append((stage, progress))
        return True

    async def complete_job(self, job_id: UUID, *, chunks: list[ChunkToSave]) -> bool:
        assert job_id == self.job_id
        self.completed_chunks = chunks
        return True

    async def fail_job(self, job_id: UUID, *, error_message: str) -> None:
        assert job_id == self.job_id
        self.failures.append(error_message)


def test_worker_runs_all_stages_and_builds_persistable_chunks() -> None:
    repository = FakeWorkerRepository(
        "# ResumeGraph\r\n\r\n## Architecture\r\n\r\nFirst.\r\n\r\nSecond."
    )
    worker = IngestionWorker(repository, chunk_max_characters=2_000)

    asyncio.run(worker.run(repository.job_id))

    assert repository.stages == [
        ("reading", 5),
        ("cleaning", 25),
        ("chunking", 55),
        ("saving", 85),
    ]
    assert repository.failures == []
    assert repository.completed_chunks is not None
    assert len(repository.completed_chunks) == 1
    chunk = repository.completed_chunks[0]
    assert chunk.chunk_index == 0
    assert chunk.heading_path == ("Architecture",)
    assert chunk.content_hash == sha256(chunk.content.encode("utf-8")).hexdigest()
    assert chunk.character_count == len(chunk.content)
    assert chunk.enabled is True


def test_worker_marks_empty_document_failed_with_safe_reason() -> None:
    repository = FakeWorkerRepository("\ufeff\x00\r\n \t")
    worker = IngestionWorker(repository, chunk_max_characters=2_000)

    with pytest.raises(DocumentProcessingFailedError) as raised:
        asyncio.run(worker.run(repository.job_id))

    assert repository.completed_chunks is None
    assert repository.failures == ["Document content is empty after deterministic cleaning."]
    assert "\x00" not in str(raised.value)


def test_worker_saves_generic_failure_without_raw_exception_details() -> None:
    repository = FakeWorkerRepository("# Fictional")

    def failing_cleaner(_content: str):
        raise RuntimeError("secret DSN and raw document")

    worker = IngestionWorker(
        repository,
        chunk_max_characters=2_000,
        cleaner=failing_cleaner,
    )

    with pytest.raises(RuntimeError):
        asyncio.run(worker.run(repository.job_id))

    assert repository.failures == ["Document processing failed."]
    assert "secret" not in repository.failures[0].lower()


def test_worker_marks_cancelled_or_timed_out_job_failed_before_propagating() -> None:
    repository = FakeWorkerRepository("# Fictional")

    def cancelling_cleaner(_content: str):
        raise asyncio.CancelledError

    worker = IngestionWorker(
        repository,
        chunk_max_characters=2_000,
        cleaner=cancelling_cleaner,
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker.run(repository.job_id))

    assert repository.completed_chunks is None
    assert repository.failures == ["Document processing was interrupted."]


def test_worker_ignores_missing_or_terminal_job() -> None:
    repository = FakeWorkerRepository(None)
    worker = IngestionWorker(repository, chunk_max_characters=2_000)

    asyncio.run(worker.run(repository.job_id))

    assert repository.stages == []
    assert repository.completed_chunks is None
    assert repository.failures == []
