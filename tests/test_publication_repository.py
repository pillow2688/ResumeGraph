import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.models import ChunkEmbedding, DocumentChunk, DocumentVersion, KnowledgeDocument
from app.repositories.publication import (
    ChunkNotEditableRepositoryError,
    PublicationIntegrityRepositoryError,
    PublicationRepository,
    VersionNotPublishableRepositoryError,
)

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, value) -> None:
        self.value = value

    def one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, value) -> None:
        self.value = value
        self.executed = []
        self.commit_count = 0

    async def execute(self, statement):
        self.executed.append(statement)
        return FakeResult(self.value)

    async def commit(self) -> None:
        self.commit_count += 1


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self.session_instance = session

    @asynccontextmanager
    async def session(self):
        yield self.session_instance


class SequenceResult:
    def __init__(self, values) -> None:
        self.values = values if isinstance(values, list) else [values]

    def one_or_none(self):
        return self.values[0] if self.values and self.values[0] is not None else None

    def scalar_one_or_none(self):
        return self.values[0] if self.values and self.values[0] is not None else None

    def scalars(self):
        return self

    def all(self):
        return self.values


class SequenceSession:
    def __init__(self, results: list[object]) -> None:
        self.results = list(results)
        self.executed = []
        self.commit_count = 0

    async def execute(self, statement):
        self.executed.append(statement)
        return SequenceResult(self.results.pop(0))

    async def commit(self) -> None:
        self.commit_count += 1


def make_row(*, status: str, enabled: bool = True):
    version = DocumentVersion(
        id=uuid4(),
        document_id=uuid4(),
        version_number=1,
        source_type="pasted_markdown",
        original_filename=None,
        raw_content="# Architecture",
        content_hash="a" * 64,
        status=status,
        created_at=NOW,
    )
    chunk = DocumentChunk(
        id=uuid4(),
        document_version_id=version.id,
        chunk_index=0,
        heading_path=["Architecture"],
        content="A bounded retry design.",
        content_hash="b" * 64,
        character_count=23,
        enabled=enabled,
        created_at=NOW,
    )
    return chunk, version


@pytest.mark.parametrize("status", ["ready_for_review", "indexing_failed", "ready_to_publish"])
def test_chunk_toggle_locks_row_and_requires_reindex(status: str) -> None:
    chunk, version = make_row(status=status)
    session = FakeSession((chunk, version))

    record = asyncio.run(
        PublicationRepository(FakeDatabase(session)).set_chunk_enabled(
            chunk.id,
            enabled=False,
        )
    )

    assert record is not None and record.enabled is False
    assert record.disabled_reason == "administrator"
    assert version.status == "ready_for_review"
    assert session.executed[0]._for_update_arg is not None
    assert session.commit_count == 1


def test_noop_chunk_toggle_does_not_invalidate_ready_version() -> None:
    chunk, version = make_row(status="ready_to_publish", enabled=True)
    session = FakeSession((chunk, version))

    record = asyncio.run(
        PublicationRepository(FakeDatabase(session)).set_chunk_enabled(chunk.id, enabled=True)
    )

    assert record is not None and record.enabled is True
    assert version.status == "ready_to_publish"
    assert session.commit_count == 0


def test_administrator_can_restore_an_ordinary_chunk_but_not_a_hard_block() -> None:
    chunk, version = make_row(status="ready_for_review", enabled=False)
    chunk.disabled_reason = "administrator"
    session = FakeSession((chunk, version))

    record = asyncio.run(
        PublicationRepository(FakeDatabase(session)).set_chunk_enabled(chunk.id, enabled=True)
    )

    assert record is not None and record.enabled is True
    assert record.disabled_reason is None

    blocked, blocked_version = make_row(status="ready_for_review", enabled=False)
    blocked.disabled_reason = "hard_block"
    blocked_session = FakeSession((blocked, blocked_version))
    with pytest.raises(ChunkNotEditableRepositoryError):
        asyncio.run(
            PublicationRepository(FakeDatabase(blocked_session)).set_chunk_enabled(
                blocked.id,
                enabled=True,
            )
        )
    assert blocked.enabled is False
    assert blocked.disabled_reason == "hard_block"


@pytest.mark.parametrize("status", ["draft", "processing", "indexing", "published", "superseded"])
def test_chunk_cannot_be_changed_outside_review_states(status: str) -> None:
    chunk, _version = make_row(status=status)
    session = FakeSession((chunk, _version))

    with pytest.raises(ChunkNotEditableRepositoryError):
        asyncio.run(
            PublicationRepository(FakeDatabase(session)).set_chunk_enabled(
                chunk.id,
                enabled=False,
            )
        )

    assert session.commit_count == 0


def test_missing_chunk_returns_none() -> None:
    session = FakeSession(None)

    result = asyncio.run(
        PublicationRepository(FakeDatabase(session)).set_chunk_enabled(
            uuid4(),
            enabled=False,
        )
    )

    assert result is None


def make_publication_rows(*, with_old: bool = False):
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
        status="ready_to_publish",
        created_at=NOW,
    )
    old_version = None
    if with_old:
        old_version = DocumentVersion(
            id=uuid4(),
            document_id=document.id,
            version_number=1,
            source_type="pasted_markdown",
            original_filename=None,
            raw_content="# Old",
            content_hash="c" * 64,
            status="published",
            created_at=NOW,
        )
        document.current_published_version_id = old_version.id
    chunk = DocumentChunk(
        id=uuid4(),
        document_version_id=version.id,
        chunk_index=0,
        heading_path=["Architecture"],
        content="A bounded retry design.",
        content_hash="b" * 64,
        character_count=23,
        enabled=True,
        created_at=NOW,
    )
    embedding = ChunkEmbedding(
        id=uuid4(),
        chunk_id=chunk.id,
        provider_name="zhipu",
        model_name="embedding-3",
        dimensions=3,
        content_hash=chunk.content_hash,
        embedding=[0.1, 0.2, 0.3],
        created_at=NOW,
    )
    return document, version, old_version, chunk, embedding


def test_publish_atomically_repoints_document_and_supersedes_old_version() -> None:
    document, version, old_version, chunk, embedding = make_publication_rows(with_old=True)
    session = SequenceSession([[(version, document)], [chunk], [embedding], [old_version]])
    repository = PublicationRepository(FakeDatabase(session))

    state = asyncio.run(
        repository.publish_version(
            version.id,
            provider_name="zhipu",
            model_name="embedding-3",
            dimensions=3,
        )
    )

    assert state is not None
    assert state.current_published_version_id == version.id
    assert document.current_published_version_id == version.id
    assert version.status == "published"
    assert old_version is not None and old_version.status == "superseded"
    assert all(statement._for_update_arg is not None for statement in session.executed)
    assert session.commit_count == 1


@pytest.mark.parametrize(
    "failure",
    ["no_enabled_chunks", "missing_embedding", "provider_mismatch", "hash_mismatch", "nan"],
)
def test_publish_rejects_incomplete_or_noncurrent_embeddings(failure: str) -> None:
    document, version, _old_version, chunk, embedding = make_publication_rows()
    if failure == "provider_mismatch":
        embedding.provider_name = "other"
    if failure == "hash_mismatch":
        embedding.content_hash = "d" * 64
    if failure == "nan":
        embedding.embedding = [0.1, float("nan"), 0.3]
    chunks = [] if failure == "no_enabled_chunks" else [chunk]
    embeddings = [] if failure in {"no_enabled_chunks", "missing_embedding"} else [embedding]
    results: list[object] = [[(version, document)], chunks]
    if chunks:
        results.append(embeddings)
    session = SequenceSession(results)

    with pytest.raises(PublicationIntegrityRepositoryError):
        asyncio.run(
            PublicationRepository(FakeDatabase(session)).publish_version(
                version.id,
                provider_name="zhipu",
                model_name="embedding-3",
                dimensions=3,
            )
        )

    assert document.current_published_version_id is None
    assert version.status == "ready_to_publish"
    assert session.commit_count == 0


def test_publish_requires_ready_to_publish_and_missing_version_returns_none() -> None:
    document, version, _old_version, _chunk, _embedding = make_publication_rows()
    version.status = "ready_for_review"
    session = SequenceSession([[(version, document)]])

    with pytest.raises(VersionNotPublishableRepositoryError):
        asyncio.run(
            PublicationRepository(FakeDatabase(session)).publish_version(
                version.id,
                provider_name="zhipu",
                model_name="embedding-3",
                dimensions=3,
            )
        )

    missing = SequenceSession([[]])
    result = asyncio.run(
        PublicationRepository(FakeDatabase(missing)).publish_version(
            uuid4(),
            provider_name="zhipu",
            model_name="embedding-3",
            dimensions=3,
        )
    )
    assert result is None


def test_unpublish_clears_pointer_and_supersedes_current_version() -> None:
    document, _version, old_version, _chunk, _embedding = make_publication_rows(with_old=True)
    session = SequenceSession([[document], [old_version]])

    state = asyncio.run(
        PublicationRepository(FakeDatabase(session)).unpublish_document(document.id)
    )

    assert state is not None and state.current_published_version_id is None
    assert document.current_published_version_id is None
    assert old_version is not None and old_version.status == "superseded"
    assert session.commit_count == 1
