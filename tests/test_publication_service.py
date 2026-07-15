import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.repositories.ingestion import DocumentChunkRecord
from app.repositories.publication import (
    ChunkNotEditableRepositoryError,
    PublicationIntegrityRepositoryError,
    PublicationRepositoryUnavailableError,
    PublicationStateRecord,
    VersionNotPublishableRepositoryError,
)
from app.services.publication import (
    ChunkNotEditableError,
    ChunkNotFoundError,
    DocumentNotFoundError,
    PublicationIntegrityError,
    PublicationService,
    PublicationUnavailableError,
    VersionNotFoundError,
    VersionNotPublishableError,
)

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def make_chunk(*, enabled: bool = True) -> DocumentChunkRecord:
    return DocumentChunkRecord(
        id=uuid4(),
        document_version_id=uuid4(),
        chunk_index=0,
        heading_path=("Architecture",),
        content="A bounded retry design.",
        content_hash="a" * 64,
        character_count=23,
        enabled=enabled,
        created_at=NOW,
    )


class FakeRepository:
    def __init__(self, result: DocumentChunkRecord | None) -> None:
        self.result = result
        self.failure: Exception | None = None
        self.calls: list[tuple[object, bool]] = []
        self.publish_calls: list[tuple[object, str, str, int]] = []
        self.unpublish_calls: list[object] = []
        self.publication_result: PublicationStateRecord | None = None

    async def set_chunk_enabled(self, chunk_id, *, enabled: bool):
        self.calls.append((chunk_id, enabled))
        if self.failure is not None:
            raise self.failure
        return self.result

    async def publish_version(
        self,
        version_id,
        *,
        provider_name: str,
        model_name: str,
        dimensions: int,
    ):
        self.publish_calls.append((version_id, provider_name, model_name, dimensions))
        if self.failure is not None:
            raise self.failure
        return self.publication_result

    async def unpublish_document(self, document_id):
        self.unpublish_calls.append(document_id)
        if self.failure is not None:
            raise self.failure
        return self.publication_result


def test_chunk_correction_is_provider_independent_and_returns_chunk_summary() -> None:
    chunk = make_chunk(enabled=False)
    repository = FakeRepository(chunk)
    service = PublicationService(
        repository,
        provider_name="zhipu",
        model_name="embedding-3",
        dimensions=1024,
        dependency_timeout_seconds=1,
    )

    response = asyncio.run(service.set_chunk_enabled(chunk.id, enabled=False))

    assert response.id == chunk.id
    assert response.enabled is False
    assert repository.calls == [(chunk.id, False)]


@pytest.mark.parametrize(
    ("repository_result", "repository_failure", "expected"),
    [
        (None, None, ChunkNotFoundError),
        (None, ChunkNotEditableRepositoryError(), ChunkNotEditableError),
        (None, PublicationRepositoryUnavailableError(), PublicationUnavailableError),
    ],
)
def test_chunk_correction_translates_repository_failures(
    repository_result,
    repository_failure,
    expected,
) -> None:
    repository = FakeRepository(repository_result)
    repository.failure = repository_failure
    service = PublicationService(
        repository,
        provider_name="zhipu",
        model_name="embedding-3",
        dimensions=1024,
        dependency_timeout_seconds=1,
    )

    with pytest.raises(expected):
        asyncio.run(service.set_chunk_enabled(uuid4(), enabled=True))


def test_publish_uses_active_generic_embedding_identity_and_unpublish_is_provider_free() -> None:
    version_id = uuid4()
    document_id = uuid4()
    repository = FakeRepository(None)
    repository.publication_result = PublicationStateRecord(
        document_id=document_id,
        current_published_version_id=version_id,
    )
    service = PublicationService(
        repository,
        provider_name="zhipu",
        model_name="embedding-3",
        dimensions=1024,
        dependency_timeout_seconds=1,
    )

    published = asyncio.run(service.publish_version(version_id))
    assert published.current_published_version_id == version_id
    assert repository.publish_calls == [(version_id, "zhipu", "embedding-3", 1024)]

    repository.publication_result = PublicationStateRecord(
        document_id=document_id,
        current_published_version_id=None,
    )
    unpublished = asyncio.run(service.unpublish_document(document_id))
    assert unpublished.current_published_version_id is None
    assert repository.unpublish_calls == [document_id]


@pytest.mark.parametrize(
    ("method", "failure", "expected"),
    [
        ("publish", None, VersionNotFoundError),
        ("publish", VersionNotPublishableRepositoryError(), VersionNotPublishableError),
        ("publish", PublicationIntegrityRepositoryError(), PublicationIntegrityError),
        ("unpublish", None, DocumentNotFoundError),
        ("unpublish", PublicationRepositoryUnavailableError(), PublicationUnavailableError),
    ],
)
def test_publication_methods_translate_safe_domain_errors(method, failure, expected) -> None:
    repository = FakeRepository(None)
    repository.failure = failure
    service = PublicationService(
        repository,
        provider_name="zhipu",
        model_name="embedding-3",
        dimensions=1024,
        dependency_timeout_seconds=1,
    )

    with pytest.raises(expected):
        if method == "publish":
            asyncio.run(service.publish_version(uuid4()))
        else:
            asyncio.run(service.unpublish_document(uuid4()))
