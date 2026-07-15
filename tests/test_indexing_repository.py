import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.models import (
    ChunkEmbedding,
    DocumentChunk,
    DocumentVersion,
    IngestionJob,
    KnowledgeDocument,
)
from app.repositories.indexing import (
    ChunkEmbeddingToSave,
    IndexingRepository,
    IndexingVersionNotProcessableRepositoryError,
)

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


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
    def __init__(self, results: list[list[object]]) -> None:
        self.results = list(results)
        self.executed: list[object] = []
        self.added: list[object] = []
        self.commit_count = 0

    async def execute(self, statement):
        self.executed.append(statement)
        return FakeResult(self.results.pop(0))

    def add(self, item: object) -> None:
        self.added.append(item)

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


def make_version(status: str = "ready_for_review"):
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


def make_job(version_id, *, status: str = "pending") -> IngestionJob:
    return IngestionJob(
        id=uuid4(),
        document_version_id=version_id,
        job_type="knowledge_indexing",
        status=status,
        stage="rule_check",
        progress=0,
        created_at=NOW,
    )


def test_create_indexing_job_locks_ready_version_and_transitions_atomically() -> None:
    document, version = make_version()
    session = FakeSession([[(version, document)], []])
    repository = IndexingRepository(FakeDatabase(session))

    result = asyncio.run(repository.create_job(version.id))

    assert result is not None and result.created is True
    assert result.record.job_type == "knowledge_indexing"
    assert result.record.stage == "rule_check"
    assert version.status == "indexing"
    assert session.executed[0]._for_update_arg is not None
    assert session.commit_count == 1


def test_same_version_returns_the_existing_active_indexing_job() -> None:
    document, version = make_version("indexing")
    job = make_job(version.id, status="processing")
    session = FakeSession([[(version, document)], [job]])

    result = asyncio.run(IndexingRepository(FakeDatabase(session)).create_job(version.id))

    assert result is not None and result.created is False
    assert result.record.id == job.id
    assert session.added == []
    assert session.commit_count == 0


@pytest.mark.parametrize("status", ["draft", "processing", "ready_to_publish", "published"])
def test_only_review_ready_or_failed_version_can_start_indexing(status: str) -> None:
    document, version = make_version(status)
    session = FakeSession([[(version, document)], []])

    with pytest.raises(IndexingVersionNotProcessableRepositoryError):
        asyncio.run(IndexingRepository(FakeDatabase(session)).create_job(version.id))


def test_enqueue_failure_marks_only_indexing_job_and_version_failed() -> None:
    _document, version = make_version("indexing")
    job = make_job(version.id)
    session = FakeSession([[(job, version)]])
    repository = IndexingRepository(FakeDatabase(session))

    asyncio.run(repository.mark_enqueue_failed(job.id, error_message="Indexing could not queue."))

    assert job.status == "failed"
    assert job.error_message == "Indexing could not queue."
    assert version.status == "indexing_failed"
    assert session.commit_count == 1


def test_begin_and_complete_indexing_job_follow_the_single_state_machine() -> None:
    _document, version = make_version("indexing")
    job = make_job(version.id)
    chunk = DocumentChunk(
        id=uuid4(),
        document_version_id=version.id,
        chunk_index=0,
        heading_path=["Architecture"],
        content="A technical decision with bounded retries.",
        content_hash="b" * 64,
        character_count=42,
        enabled=True,
        created_at=NOW,
    )
    embedding = ChunkEmbedding(
        id=uuid4(),
        chunk_id=chunk.id,
        embedding=[0.1, 0.2, 0.3],
        provider_name="fake-provider",
        model_name="fake-embedding",
        dimensions=3,
        content_hash=chunk.content_hash,
        created_at=NOW,
    )
    session = FakeSession([[(job, version)], [chunk], [(job, version)], [chunk], [embedding]])
    repository = IndexingRepository(FakeDatabase(session))

    item = asyncio.run(repository.begin_job(job.id))

    assert item is not None
    assert item.document_version_id == version.id
    assert item.chunks[0].content_hash == "b" * 64
    assert job.status == "processing"
    assert job.stage == "rule_check"
    assert job.progress == 5

    completed = asyncio.run(
        repository.complete_job(
            job.id,
            provider_name="fake-provider",
            model_name="fake-embedding",
            dimensions=3,
        )
    )
    assert completed is True
    assert job.status == "completed"
    assert job.stage == "saving"
    assert job.progress == 100
    assert version.status == "ready_to_publish"


@pytest.mark.parametrize(
    ("enabled_chunks", "embedding_kind"),
    [
        (False, "missing"),
        (True, "missing"),
        (True, "hash_mismatch"),
        (True, "dimension_mismatch"),
        (True, "provider_mismatch"),
    ],
)
def test_complete_job_refuses_versions_without_a_complete_valid_embedding_set(
    enabled_chunks: bool,
    embedding_kind: str,
) -> None:
    _document, version = make_version("indexing")
    job = make_job(version.id, status="processing")
    chunk = DocumentChunk(
        id=uuid4(),
        document_version_id=version.id,
        chunk_index=0,
        heading_path=["Architecture"],
        content="A technical decision with bounded retries.",
        content_hash="b" * 64,
        character_count=42,
        enabled=True,
        created_at=NOW,
    )
    embedding = ChunkEmbedding(
        id=uuid4(),
        chunk_id=chunk.id,
        embedding=[0.1, 0.2, 0.3],
        provider_name=(
            "other-provider" if embedding_kind == "provider_mismatch" else "fake-provider"
        ),
        model_name="fake-embedding",
        dimensions=3,
        content_hash=("c" * 64 if embedding_kind == "hash_mismatch" else chunk.content_hash),
        created_at=NOW,
    )
    if embedding_kind == "dimension_mismatch":
        embedding.dimensions = 2
    query_results: list[list[object]] = [
        [(job, version)],
        [chunk] if enabled_chunks else [],
    ]
    if enabled_chunks:
        query_results.append([] if embedding_kind == "missing" else [embedding])
    session = FakeSession(query_results)

    completed = asyncio.run(
        IndexingRepository(FakeDatabase(session)).complete_job(
            job.id,
            provider_name="fake-provider",
            model_name="fake-embedding",
            dimensions=3,
        )
    )

    assert completed is False
    assert job.status == "processing"
    assert version.status == "indexing"
    assert session.commit_count == 0


def test_failed_indexing_job_never_restores_document_to_draft() -> None:
    _document, version = make_version("indexing")
    job = make_job(version.id, status="processing")
    session = FakeSession([[(job, version)]])
    repository = IndexingRepository(FakeDatabase(session))

    asyncio.run(repository.fail_job(job.id, error_message="Knowledge indexing failed."))

    assert job.status == "failed"
    assert version.status == "indexing_failed"
    assert job.error_message == "Knowledge indexing failed."


def test_embedding_save_persists_only_enabled_hash_matching_dimensioned_vectors() -> None:
    _document, version = make_version("indexing")
    job = make_job(version.id, status="processing")
    chunk = DocumentChunk(
        id=uuid4(),
        document_version_id=version.id,
        chunk_index=0,
        heading_path=["Architecture"],
        content="A safe technical chunk.",
        content_hash="b" * 64,
        character_count=23,
        enabled=True,
        created_at=NOW,
    )
    session = FakeSession([[(job, version)], [chunk], []])
    repository = IndexingRepository(FakeDatabase(session))

    saved = asyncio.run(
        repository.save_embeddings(
            job.id,
            embeddings=[
                ChunkEmbeddingToSave(
                    chunk_id=chunk.id,
                    embedding=(0.1, 0.2, 0.3),
                    provider_name="fake-provider",
                    model_name="fake-embedding",
                    dimensions=3,
                    content_hash=chunk.content_hash,
                )
            ],
        )
    )

    assert saved is True
    assert len(session.added) == 1
    embedding = session.added[0]
    assert embedding.chunk_id == chunk.id
    assert embedding.content_hash == chunk.content_hash
    assert embedding.provider_name == "fake-provider"
    assert embedding.dimensions == 3
    assert session.commit_count == 1


@pytest.mark.parametrize(
    ("enabled", "content_hash", "dimensions", "vector"),
    [
        (False, "b" * 64, 3, (0.1, 0.2, 0.3)),
        (True, "c" * 64, 3, (0.1, 0.2, 0.3)),
        (True, "b" * 64, 2, (0.1, 0.2, 0.3)),
    ],
)
def test_embedding_save_rejects_disabled_hash_mismatched_or_wrong_dimension_chunks(
    enabled: bool,
    content_hash: str,
    dimensions: int,
    vector: tuple[float, ...],
) -> None:
    _document, version = make_version("indexing")
    job = make_job(version.id, status="processing")
    chunk = DocumentChunk(
        id=uuid4(),
        document_version_id=version.id,
        chunk_index=0,
        heading_path=["Architecture"],
        content="A technical chunk.",
        content_hash="b" * 64,
        character_count=18,
        enabled=enabled,
        created_at=NOW,
    )
    session = FakeSession([[(job, version)], [chunk]])
    repository = IndexingRepository(FakeDatabase(session))

    with pytest.raises(ValueError):
        asyncio.run(
            repository.save_embeddings(
                job.id,
                embeddings=[
                    ChunkEmbeddingToSave(
                        chunk_id=chunk.id,
                        embedding=vector,
                        provider_name="fake-provider",
                        model_name="fake-embedding",
                        dimensions=dimensions,
                        content_hash=content_hash,
                    )
                ],
            )
        )

    assert session.added == []
    assert session.commit_count == 0
