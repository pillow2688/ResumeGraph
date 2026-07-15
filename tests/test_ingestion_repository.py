import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.models import DocumentVersion, IngestionJob, KnowledgeDocument
from app.repositories.ingestion import (
    ChunkToSave,
    DocumentVersionNotProcessableRepositoryError,
    IngestionRepository,
    IngestionRepositoryUnavailableError,
)

NOW = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def one_or_none(self):
        return self.values[0] if self.values else None

    def scalar_one_or_none(self):
        return self.values[0] if self.values else None

    def scalars(self):
        return self

    def all(self):
        return self.values


class FakeSession:
    def __init__(
        self,
        *,
        results: list[list[object]],
        error: Exception | None = None,
    ) -> None:
        self.results = list(results)
        self.error = error
        self.executed: list[object] = []
        self.added: list[object] = []
        self.commit_count = 0

    async def execute(self, statement):
        self.executed.append(statement)
        if self.error is not None:
            raise self.error
        return FakeResult(self.results.pop(0))

    def add(self, item: object) -> None:
        self.added.append(item)

    def add_all(self, items: list[object]) -> None:
        self.added.extend(items)

    async def flush(self) -> None:
        for item in self.added:
            if isinstance(item, IngestionJob) and item.created_at is None:
                item.created_at = NOW

    async def refresh(self, _item: object) -> None:
        pass

    async def commit(self) -> None:
        self.commit_count += 1


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self.session_instance = session

    @asynccontextmanager
    async def session(self):
        yield self.session_instance


def make_version(status: str = "draft") -> tuple[KnowledgeDocument, DocumentVersion]:
    document = KnowledgeDocument(
        id=uuid4(),
        project_id=uuid4(),
        title="Architecture",
        created_at=NOW,
        updated_at=NOW,
    )
    version = DocumentVersion(
        id=uuid4(),
        document_id=document.id,
        version_number=2,
        source_type="pasted_markdown",
        original_filename=None,
        raw_content="# Architecture",
        content_hash="a" * 64,
        status=status,
        created_at=NOW,
    )
    return document, version


def test_create_job_locks_version_and_transitions_it_atomically() -> None:
    document, version = make_version()
    session = FakeSession(results=[[(version, document)], []])
    repository = IngestionRepository(FakeDatabase(session))

    result = asyncio.run(repository.create_job(version.id))

    assert result is not None and result.created is True
    assert result.record.document_title == "Architecture"
    assert result.record.status == "pending"
    assert version.status == "processing"
    assert session.executed[0]._for_update_arg is not None
    assert len(session.added) == 1
    assert session.commit_count == 1


def test_create_job_returns_existing_active_job_without_reenqueueing() -> None:
    document, version = make_version("processing")
    job = IngestionJob(
        id=uuid4(),
        document_version_id=version.id,
        job_type="document_processing",
        status="processing",
        stage="cleaning",
        progress=25,
        created_at=NOW,
        started_at=NOW,
    )
    session = FakeSession(results=[[(version, document)], [job]])
    repository = IngestionRepository(FakeDatabase(session))

    result = asyncio.run(repository.create_job(version.id))

    assert result is not None and result.created is False
    assert result.record.id == job.id
    assert session.added == []
    assert session.commit_count == 0


def test_ready_version_cannot_be_processed_again() -> None:
    document, version = make_version("ready_for_review")
    repository = IngestionRepository(FakeDatabase(FakeSession(results=[[(version, document)]])))

    with pytest.raises(DocumentVersionNotProcessableRepositoryError):
        asyncio.run(repository.create_job(version.id))


def test_repository_database_errors_are_sanitized() -> None:
    session = FakeSession(results=[], error=SQLAlchemyError("secret postgresql DSN"))
    repository = IngestionRepository(FakeDatabase(session))

    with pytest.raises(IngestionRepositoryUnavailableError) as raised:
        asyncio.run(repository.get_job(uuid4()))

    assert "secret" not in str(raised.value).lower()
    assert "postgresql" not in str(raised.value).lower()


def test_begin_job_sets_processing_reading_and_started_at() -> None:
    _document, version = make_version("processing")
    job = IngestionJob(
        id=uuid4(),
        document_version_id=version.id,
        job_type="document_processing",
        status="pending",
        stage="reading",
        progress=0,
        created_at=NOW,
    )
    session = FakeSession(results=[[(job, version)]])
    repository = IngestionRepository(FakeDatabase(session))

    item = asyncio.run(repository.begin_job(job.id))

    assert item is not None and item.raw_content == "# Architecture"
    assert job.status == "processing"
    assert job.stage == "reading"
    assert job.progress == 5
    assert job.started_at is not None
    assert session.commit_count == 1


def test_document_processing_repository_rejects_misrouted_indexing_job() -> None:
    _document, version = make_version("indexing")
    job = IngestionJob(
        id=uuid4(),
        document_version_id=version.id,
        job_type="knowledge_indexing",
        status="pending",
        stage="rule_check",
        progress=0,
        created_at=NOW,
    )
    session = FakeSession(results=[[(job, version)]])
    repository = IngestionRepository(FakeDatabase(session))

    item = asyncio.run(repository.begin_job(job.id))

    assert item is None
    assert job.status == "pending"
    assert job.stage == "rule_check"
    assert version.status == "indexing"
    assert session.commit_count == 0


def test_document_processing_start_does_not_reuse_active_indexing_job() -> None:
    document, version = make_version("indexing")
    session = FakeSession(results=[[(version, document)], []])
    repository = IngestionRepository(FakeDatabase(session))

    with pytest.raises(DocumentVersionNotProcessableRepositoryError):
        asyncio.run(repository.create_job(version.id))


def test_complete_job_replaces_chunks_and_completes_version_atomically() -> None:
    _document, version = make_version("processing")
    job = IngestionJob(
        id=uuid4(),
        document_version_id=version.id,
        job_type="document_processing",
        status="processing",
        stage="saving",
        progress=85,
        created_at=NOW,
        started_at=NOW,
    )
    session = FakeSession(results=[[(job, version)], []])
    repository = IngestionRepository(FakeDatabase(session))

    completed = asyncio.run(
        repository.complete_job(
            job.id,
            chunks=[
                ChunkToSave(
                    chunk_index=0,
                    heading_path=("Architecture",),
                    content="## Architecture\n\nContent",
                    content_hash="b" * 64,
                    character_count=25,
                )
            ],
        )
    )

    assert completed is True
    assert len(session.added) == 1
    chunk = session.added[0]
    assert chunk.chunk_index == 0
    assert chunk.heading_path == ["Architecture"]
    assert job.status == "completed"
    assert job.progress == 100
    assert job.finished_at is not None
    assert version.status == "ready_for_review"
    assert session.commit_count == 1


def test_fail_job_records_safe_message_and_restores_draft() -> None:
    _document, version = make_version("processing")
    job = IngestionJob(
        id=uuid4(),
        document_version_id=version.id,
        job_type="document_processing",
        status="processing",
        stage="chunking",
        progress=55,
        created_at=NOW,
        started_at=NOW,
    )
    session = FakeSession(results=[[(job, version)]])
    repository = IngestionRepository(FakeDatabase(session))

    asyncio.run(repository.fail_job(job.id, error_message="Document processing failed."))

    assert job.status == "failed"
    assert job.error_message == "Document processing failed."
    assert job.finished_at is not None
    assert version.status == "draft"
    assert session.commit_count == 1
