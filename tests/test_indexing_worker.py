import asyncio
from uuid import UUID, uuid4

import pytest

from app.infrastructure.embedding import (
    EmbeddingProvider,
    FakeEmbeddingProvider,
    UnconfiguredEmbeddingProvider,
)
from app.repositories.indexing import (
    ChunkEmbeddingToSave,
    ChunkQualityUpdate,
    IndexingChunk,
    IndexingWorkItem,
)
from app.schemas.indexing import ChunkQualityDecision
from app.services.indexing_worker import (
    IndexingWorker,
    KnowledgeIndexingFailedError,
)


def make_chunk(
    content: str,
    *,
    index: int,
    enabled: bool = True,
    auto_indexable: bool | None = None,
    disabled_reason: str | None = None,
) -> IndexingChunk:
    return IndexingChunk(
        id=uuid4(),
        chunk_index=index,
        content=content,
        content_hash=(str(index + 1) * 64)[:64],
        enabled=enabled,
        auto_indexable=auto_indexable,
        disabled_reason=disabled_reason,
    )


def decision(chunk_id: UUID, *, is_indexable: bool = True) -> ChunkQualityDecision:
    return ChunkQualityDecision(
        chunk_id=chunk_id,
        is_indexable=is_indexable,
        issues=[],
        knowledge_type="technical_decision",
        topics=["RAG"],
        technologies=["FastAPI"],
        reason="包含明确的技术决策",
    )


class FakeRepository:
    def __init__(self, chunks: list[IndexingChunk]) -> None:
        self.job_id = uuid4()
        self.version_id = uuid4()
        self.item = IndexingWorkItem(
            job_id=self.job_id,
            document_version_id=self.version_id,
            chunks=tuple(chunks),
        )
        self.stages: list[tuple[str, int]] = []
        self.quality_updates: list[ChunkQualityUpdate] | None = None
        self.embeddings: list[ChunkEmbeddingToSave] | None = None
        self.completed = False
        self.completion_identity: tuple[str, str, int] | None = None
        self.failures: list[str] = []

    async def begin_job(self, job_id: UUID):
        assert job_id == self.job_id
        return self.item

    async def set_stage(self, job_id: UUID, *, stage: str, progress: int) -> bool:
        assert job_id == self.job_id
        self.stages.append((stage, progress))
        return True

    async def save_quality_results(
        self,
        job_id: UUID,
        *,
        updates: list[ChunkQualityUpdate],
    ) -> bool:
        assert job_id == self.job_id
        self.quality_updates = updates
        return True

    async def save_embeddings(
        self,
        job_id: UUID,
        *,
        embeddings: list[ChunkEmbeddingToSave],
    ) -> bool:
        assert job_id == self.job_id
        self.embeddings = embeddings
        return True

    async def complete_job(
        self,
        job_id: UUID,
        *,
        provider_name: str,
        model_name: str,
        dimensions: int,
    ) -> bool:
        assert job_id == self.job_id
        self.completed = True
        self.completion_identity = (provider_name, model_name, dimensions)
        return True

    async def fail_job(self, job_id: UUID, *, error_message: str) -> None:
        assert job_id == self.job_id
        self.failures.append(error_message)


class FakeQualityProvider:
    model_name = "deepseek-v4-pro"

    def __init__(self, decisions: list[ChunkQualityDecision]) -> None:
        self.decisions = decisions
        self.calls = 0

    async def evaluate(self, _rule_results):
        self.calls += 1
        return self.decisions


class RecordingEmbeddingProvider:
    provider_name = "recording-provider"
    model_name = "recording-embedding"
    dimensions = 3

    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]


def make_embedding_provider(
    *,
    configured: bool = True,
    provider: EmbeddingProvider | None = None,
) -> EmbeddingProvider:
    return provider or (
        FakeEmbeddingProvider(
            provider_name="fake-provider",
            model_name="fake-embedding",
            dimensions=3,
        )
        if configured
        else UnconfiguredEmbeddingProvider()
    )


def test_worker_applies_rules_before_llm_and_embeds_only_safe_enabled_chunks() -> None:
    secret = make_chunk("api_key = sk-fictional1234567890abcdef", index=0)
    pii = make_chunk(
        "Contact fictional.person@example.test or 13800138000 for implementation details.",
        index=1,
    )
    clean = make_chunk(
        "The architecture uses bounded retries and explicit timeouts.",
        index=2,
    )
    repository = FakeRepository([secret, pii, clean])
    judge = FakeQualityProvider([decision(pii.id), decision(clean.id)])
    worker = IndexingWorker(repository, judge, make_embedding_provider())

    asyncio.run(worker.run(repository.job_id))

    assert repository.stages == [
        ("llm_quality_check", 30),
        ("embedding", 60),
        ("saving", 85),
    ]
    assert repository.completed is True
    assert repository.completion_identity == ("fake-provider", "fake-embedding", 3)
    assert repository.failures == []
    assert repository.quality_updates is not None
    updates = {item.chunk_id: item for item in repository.quality_updates}
    assert updates[secret.id].auto_indexable is False
    assert updates[secret.id].enabled is False
    assert updates[secret.id].disabled_reason == "hard_block"
    assert updates[pii.id].auto_indexable is False
    assert updates[pii.id].enabled is False
    assert updates[pii.id].disabled_reason == "quality"
    assert updates[clean.id].auto_indexable is True
    assert updates[clean.id].enabled is True
    assert updates[clean.id].disabled_reason is None
    assert "sk-fictional" not in repr(repository.quality_updates)
    assert "fictional.person" not in repr(repository.quality_updates)
    assert repository.embeddings is not None
    assert [item.chunk_id for item in repository.embeddings] == [clean.id]
    assert repository.embeddings[0].content_hash == clean.content_hash
    assert repository.embeddings[0].provider_name == "fake-provider"
    assert repository.embeddings[0].model_name == "fake-embedding"
    assert repository.embeddings[0].dimensions == 3


def test_rerun_preserves_existing_admin_enabled_choice_for_non_sensitive_chunks() -> None:
    disabled = make_chunk(
        "A clean chunk that an administrator disabled.",
        index=0,
        enabled=False,
        auto_indexable=False,
        disabled_reason="administrator",
    )
    enabled = make_chunk(
        "A clean chunk that remains enabled.",
        index=1,
        enabled=True,
        auto_indexable=True,
    )
    repository = FakeRepository([disabled, enabled])
    judge = FakeQualityProvider([decision(disabled.id), decision(enabled.id)])
    worker = IndexingWorker(repository, judge, make_embedding_provider())

    asyncio.run(worker.run(repository.job_id))

    assert repository.quality_updates is not None
    updates = {item.chunk_id: item for item in repository.quality_updates}
    assert updates[disabled.id].auto_indexable is True
    assert updates[disabled.id].enabled is None
    assert updates[disabled.id].disabled_reason is None
    assert updates[enabled.id].enabled is None
    assert repository.embeddings is not None
    assert [item.chunk_id for item in repository.embeddings] == [enabled.id]


def test_rerun_preserves_admin_enabled_pii_but_redacts_embedding_payload() -> None:
    pii = make_chunk(
        "Contact fictional.person@example.test or 13800138000 for implementation details.",
        index=0,
        enabled=True,
        auto_indexable=False,
    )
    repository = FakeRepository([pii])
    embedding_provider = RecordingEmbeddingProvider()
    worker = IndexingWorker(
        repository,
        FakeQualityProvider([decision(pii.id)]),
        make_embedding_provider(provider=embedding_provider),
    )

    asyncio.run(worker.run(repository.job_id))

    assert repository.quality_updates is not None
    update = repository.quality_updates[0]
    assert update.auto_indexable is False
    assert update.enabled is None
    assert embedding_provider.texts == [
        "Contact [REDACTED_EMAIL] or [REDACTED_PHONE] for implementation details."
    ]
    assert repository.embeddings is not None
    assert repository.embeddings[0].content_hash == pii.content_hash


def test_unconfigured_embedding_provider_fails_job_without_fake_fallback() -> None:
    clean = make_chunk("A clean technical chunk.", index=0)
    repository = FakeRepository([clean])
    judge = FakeQualityProvider([decision(clean.id)])
    worker = IndexingWorker(
        repository,
        judge,
        make_embedding_provider(configured=False),
    )

    with pytest.raises(KnowledgeIndexingFailedError):
        asyncio.run(worker.run(repository.job_id))

    assert repository.completed is False
    assert judge.calls == 0
    assert repository.embeddings is None
    assert repository.failures == ["embedding_provider_unavailable"]


def test_worker_rejects_judge_ids_outside_the_current_server_batch() -> None:
    clean = make_chunk("A clean technical chunk.", index=0)
    repository = FakeRepository([clean])
    worker = IndexingWorker(
        repository,
        FakeQualityProvider([decision(uuid4())]),
        make_embedding_provider(),
    )

    with pytest.raises(KnowledgeIndexingFailedError):
        asyncio.run(worker.run(repository.job_id))

    assert repository.quality_updates is None
    assert repository.embeddings is None
    assert repository.failures == ["Knowledge indexing failed."]
