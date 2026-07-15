import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.repositories.deduplication import (
    DeduplicationCandidate,
    DeduplicationChange,
    DeduplicationEmbedding,
    DeduplicationScope,
    DeduplicationSnapshot,
)
from app.services.deduplication import DeduplicationService

NOW = datetime(2026, 7, 15, 16, 0, tzinfo=UTC)


def candidate(
    *,
    content_hash: str,
    created_offset: int,
    enabled: bool = True,
    disabled_reason: str | None = None,
    embedding: tuple[float, ...] | None = (0.1, 0.2, 0.3),
    content: str = "Fictional education evidence with enough detail for indexing.",
    chunk_id: UUID | None = None,
) -> DeduplicationCandidate:
    return DeduplicationCandidate(
        chunk_id=chunk_id or uuid4(),
        content=content,
        content_hash=content_hash,
        created_at=NOW + timedelta(seconds=created_offset),
        enabled=enabled,
        disabled_reason=disabled_reason,
        quality_issues=(
            ({"source": "deduplication", "code": "exact_duplicate", "severity": "hard_block"},)
            if disabled_reason == "exact_duplicate"
            else ()
        ),
        embedding=embedding,
    )


class FakeRepository:
    def __init__(self, candidates: list[DeduplicationCandidate]) -> None:
        self.document_id = uuid4()
        self.version_id = uuid4()
        self.candidates = candidates
        self.load_scopes: list[DeduplicationScope] = []
        self.applies: list[tuple[list[DeduplicationChange], list[DeduplicationEmbedding]]] = []

    async def load_scope(
        self,
        scope: DeduplicationScope,
        *,
        provider_name: str,
        model_name: str,
        dimensions: int,
    ) -> DeduplicationSnapshot:
        assert (provider_name, model_name, dimensions) == ("zhipu", "embedding-3", 3)
        self.load_scopes.append(scope)
        return DeduplicationSnapshot(
            revision=((self.document_id, self.version_id),),
            candidates=tuple(self.candidates),
        )

    async def apply_scope(
        self,
        scope: DeduplicationScope,
        *,
        expected_revision: tuple[tuple[UUID, UUID], ...],
        changes: list[DeduplicationChange],
        embeddings: list[DeduplicationEmbedding],
        provider_name: str,
        model_name: str,
        dimensions: int,
    ) -> bool:
        assert expected_revision == ((self.document_id, self.version_id),)
        assert (provider_name, model_name, dimensions) == ("zhipu", "embedding-3", 3)
        self.applies.append((changes, embeddings))
        changes_by_id = {item.chunk_id: item for item in changes}
        embeddings_by_id = {item.chunk_id: item.embedding for item in embeddings}
        self.candidates = [
            DeduplicationCandidate(
                chunk_id=item.chunk_id,
                content=item.content,
                content_hash=item.content_hash,
                created_at=item.created_at,
                enabled=changes_by_id[item.chunk_id].enabled,
                disabled_reason=changes_by_id[item.chunk_id].disabled_reason,
                quality_issues=changes_by_id[item.chunk_id].quality_issues,
                embedding=(
                    embeddings_by_id.get(item.chunk_id)
                    if changes_by_id[item.chunk_id].enabled
                    else None
                )
                or (item.embedding if changes_by_id[item.chunk_id].enabled else None),
            )
            for item in self.candidates
        ]
        return True


class RecordingEmbeddingProvider:
    provider_name = "zhipu"
    model_name = "embedding-3"
    dimensions = 3

    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [[0.7, 0.8, 0.9] for _ in texts]


def make_service(
    repository: FakeRepository,
    provider: RecordingEmbeddingProvider | None = None,
) -> tuple[DeduplicationService, RecordingEmbeddingProvider]:
    active_provider = provider or RecordingEmbeddingProvider()
    return (
        DeduplicationService(
            repository,
            active_provider,
            dependency_timeout_seconds=1,
        ),
        active_provider,
    )


def test_profile_scope_keeps_one_stable_canonical_and_one_active_embedding() -> None:
    content_hash = "a" * 64
    canonical = candidate(content_hash=content_hash, created_offset=0)
    duplicate = candidate(content_hash=content_hash, created_offset=1)
    repository = FakeRepository([duplicate, canonical])
    service, provider = make_service(repository)

    result = asyncio.run(service.rebuild_profile_scope())

    assert result.canonical_count == 1
    assert result.duplicate_count == 1
    assert provider.texts == []
    changes, embeddings = repository.applies[-1]
    by_id = {item.chunk_id: item for item in changes}
    assert by_id[canonical.chunk_id].enabled is True
    assert by_id[canonical.chunk_id].disabled_reason is None
    assert all(
        issue.get("code") != "exact_duplicate" for issue in by_id[canonical.chunk_id].quality_issues
    )
    assert by_id[duplicate.chunk_id].enabled is False
    assert by_id[duplicate.chunk_id].disabled_reason == "exact_duplicate"
    assert sum(item.enabled for item in repository.candidates) == 1
    assert sum(item.embedding is not None for item in repository.candidates) == 1
    assert embeddings == []


def test_project_scope_is_explicit_and_different_projects_are_never_combined() -> None:
    repository = FakeRepository([candidate(content_hash="b" * 64, created_offset=0)])
    service, _provider = make_service(repository)
    project_a = uuid4()
    project_b = uuid4()

    asyncio.run(service.rebuild_project_scope(project_a))
    asyncio.run(service.rebuild_project_scope(project_b))

    assert repository.load_scopes == [
        DeduplicationScope(scope="project", project_id=project_a),
        DeduplicationScope(scope="project", project_id=project_b),
    ]


def test_different_hashes_are_not_deduplicated_even_when_text_is_similar() -> None:
    repository = FakeRepository(
        [
            candidate(content_hash="c" * 64, created_offset=0, content="Redis stores sessions."),
            candidate(
                content_hash="d" * 64,
                created_offset=1,
                content="Redis stores session data.",
            ),
        ]
    )
    service, _provider = make_service(repository)

    result = asyncio.run(service.rebuild_profile_scope())

    assert result.canonical_count == 2
    assert result.duplicate_count == 0
    assert all(item.enabled for item in repository.candidates)


def test_hard_block_and_administrator_disabled_chunks_are_never_reenabled() -> None:
    safe = candidate(content_hash="e" * 64, created_offset=0)
    hard = candidate(
        content_hash="e" * 64,
        created_offset=-2,
        enabled=False,
        disabled_reason="hard_block",
        embedding=None,
    )
    administrator = candidate(
        content_hash="e" * 64,
        created_offset=-1,
        enabled=False,
        disabled_reason="administrator",
        embedding=None,
    )
    repository = FakeRepository([hard, administrator, safe])
    service, _provider = make_service(repository)

    asyncio.run(service.rebuild_profile_scope())

    by_id = {item.chunk_id: item for item in repository.candidates}
    assert by_id[hard.chunk_id].enabled is False
    assert by_id[hard.chunk_id].disabled_reason == "hard_block"
    assert by_id[administrator.chunk_id].enabled is False
    assert by_id[administrator.chunk_id].disabled_reason == "administrator"
    assert by_id[safe.chunk_id].enabled is True


def test_new_canonical_without_vector_uses_existing_embedding_provider_then_is_idempotent() -> None:
    former_duplicate = candidate(
        content_hash="f" * 64,
        created_offset=0,
        enabled=False,
        disabled_reason="exact_duplicate",
        embedding=None,
        content="Contact fictional.person@example.test about the fictional degree.",
    )
    repository = FakeRepository([former_duplicate])
    service, provider = make_service(repository)

    first = asyncio.run(service.rebuild_profile_scope())
    second = asyncio.run(service.rebuild_profile_scope())

    assert first.generated_embedding_count == 1
    assert second.generated_embedding_count == 0
    assert provider.texts == ["Contact [REDACTED_EMAIL] about the fictional degree."]
    assert repository.candidates[0].enabled is True
    assert repository.candidates[0].embedding == (0.7, 0.8, 0.9)
