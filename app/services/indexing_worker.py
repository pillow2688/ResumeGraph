import asyncio
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.infrastructure.deepseek_quality import QualityProviderError
from app.infrastructure.embedding import (
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingProviderNotConfiguredError,
)
from app.quality.rules import (
    ChunkRuleInput,
    RuleConfig,
    RuleIssueCode,
    RuleSeverity,
    validate_chunks,
)
from app.repositories.indexing import (
    ChunkEmbeddingToSave,
    ChunkQualityUpdate,
    IndexingWorkItem,
)
from app.schemas.indexing import ChunkQualityDecision


class KnowledgeIndexingFailedError(Exception):
    pass


class _InvalidQualityBatchError(ValueError):
    pass


class _NoEnabledChunksError(ValueError):
    pass


class IndexingWorkerRepositoryBackend(Protocol):
    async def begin_job(self, job_id: UUID) -> IndexingWorkItem | None: ...

    async def set_stage(self, job_id: UUID, *, stage: str, progress: int) -> bool: ...

    async def save_quality_results(
        self,
        job_id: UUID,
        *,
        updates: list[ChunkQualityUpdate],
    ) -> bool: ...

    async def save_embeddings(
        self,
        job_id: UUID,
        *,
        embeddings: list[ChunkEmbeddingToSave],
    ) -> bool: ...

    async def complete_job(
        self,
        job_id: UUID,
        *,
        provider_name: str,
        model_name: str,
        dimensions: int,
    ) -> bool: ...

    async def fail_job(self, job_id: UUID, *, error_message: str) -> None: ...


class QualityProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    async def evaluate(self, rule_results) -> list[ChunkQualityDecision]: ...


class IndexingWorker:
    def __init__(
        self,
        repository: IndexingWorkerRepositoryBackend,
        quality_provider: QualityProvider,
        embedding_provider: EmbeddingProvider,
        *,
        rule_config: RuleConfig | None = None,
    ) -> None:
        self._repository = repository
        self._quality_provider = quality_provider
        self._embedding_provider = embedding_provider
        self._rule_config = rule_config or RuleConfig()

    async def run(self, job_id: UUID) -> None:
        item = await self._repository.begin_job(job_id)
        if item is None:
            return
        try:
            if self._embedding_provider.dimensions <= 0:
                raise EmbeddingProviderNotConfiguredError
            if not item.chunks:
                raise _NoEnabledChunksError
            rule_results = validate_chunks(
                [
                    ChunkRuleInput(
                        chunk_id=chunk.id,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        content_hash=chunk.content_hash,
                    )
                    for chunk in item.chunks
                ],
                config=self._rule_config,
            )

            await self._repository.set_stage(
                job_id,
                stage="llm_quality_check",
                progress=30,
            )
            decisions = await self._quality_provider.evaluate(rule_results)
            expected_decision_ids = {
                result.chunk_id for result in rule_results if not result.hard_blocked
            }
            decision_ids = [decision.chunk_id for decision in decisions]
            if (
                len(decision_ids) != len(set(decision_ids))
                or set(decision_ids) != expected_decision_ids
            ):
                raise _InvalidQualityBatchError
            decision_by_id = {decision.chunk_id: decision for decision in decisions}

            checked_at = datetime.now(UTC)
            chunks_by_id = {chunk.id: chunk for chunk in item.chunks}
            embedding_content_by_id: dict[UUID, str] = {}
            effective_enabled: dict[UUID, bool] = {}
            updates: list[ChunkQualityUpdate] = []
            for result in rule_results:
                chunk = chunks_by_id[result.chunk_id]
                rule_issues = tuple(
                    {
                        "source": "rule",
                        "code": issue.code.value,
                        "severity": issue.severity.value,
                    }
                    for issue in result.issues
                )
                if result.hard_blocked:
                    auto_indexable = False
                    enabled_update: bool | None = False
                    disabled_reason_update = (
                        "hard_block"
                        if any(
                            issue.severity is RuleSeverity.HARD_BLOCK
                            and issue.code is not RuleIssueCode.EXACT_DUPLICATE
                            for issue in result.issues
                        )
                        else "exact_duplicate"
                    )
                    metadata: dict[str, object] = {}
                    quality_model = "deterministic-rules"
                    reason = "Blocked by deterministic safety or duplicate-content rules."
                    issues = rule_issues
                else:
                    decision = decision_by_id[result.chunk_id]
                    auto_indexable = (
                        False if result.contains_personal_contact else decision.is_indexable
                    )
                    enabled_update = auto_indexable if chunk.auto_indexable is None else None
                    disabled_reason_update = "quality" if enabled_update is False else None
                    if result.redacted_content is None:
                        raise _InvalidQualityBatchError
                    embedding_content_by_id[result.chunk_id] = result.redacted_content
                    metadata = {
                        "knowledge_type": decision.knowledge_type,
                        "topics": decision.topics,
                        "technologies": decision.technologies,
                    }
                    quality_model = self._quality_provider.model_name
                    reason = decision.reason
                    issues = rule_issues + tuple(
                        {
                            "source": "llm",
                            "code": issue,
                            "severity": "warning",
                        }
                        for issue in decision.issues
                    )
                effective_enabled[result.chunk_id] = (
                    enabled_update if enabled_update is not None else chunk.enabled
                )
                updates.append(
                    ChunkQualityUpdate(
                        chunk_id=result.chunk_id,
                        auto_indexable=auto_indexable,
                        enabled=enabled_update,
                        disabled_reason=disabled_reason_update,
                        quality_issues=issues,
                        extracted_metadata=metadata,
                        quality_checked_at=checked_at,
                        quality_model=quality_model,
                        quality_reason=reason,
                    )
                )

            if not await self._repository.save_quality_results(job_id, updates=updates):
                raise KnowledgeIndexingFailedError

            chunks_to_embed = [chunk for chunk in item.chunks if effective_enabled[chunk.id]]
            if not chunks_to_embed:
                raise _NoEnabledChunksError
            await self._repository.set_stage(job_id, stage="embedding", progress=60)
            vectors = await self._embedding_provider.embed_texts(
                [embedding_content_by_id[chunk.id] for chunk in chunks_to_embed]
            )
            embeddings = [
                ChunkEmbeddingToSave(
                    chunk_id=chunk.id,
                    embedding=tuple(vector),
                    provider_name=self._embedding_provider.provider_name,
                    model_name=self._embedding_provider.model_name,
                    dimensions=self._embedding_provider.dimensions,
                    content_hash=chunk.content_hash,
                )
                for chunk, vector in zip(chunks_to_embed, vectors, strict=True)
            ]
            await self._repository.set_stage(job_id, stage="saving", progress=85)
            if not await self._repository.save_embeddings(job_id, embeddings=embeddings):
                raise KnowledgeIndexingFailedError
            if not await self._repository.complete_job(
                job_id,
                provider_name=self._embedding_provider.provider_name,
                model_name=self._embedding_provider.model_name,
                dimensions=self._embedding_provider.dimensions,
            ):
                raise KnowledgeIndexingFailedError
        except asyncio.CancelledError:
            await asyncio.shield(
                self._repository.fail_job(
                    job_id,
                    error_message="Knowledge indexing was interrupted.",
                )
            )
            raise
        except EmbeddingProviderNotConfiguredError as error:
            await self._repository.fail_job(
                job_id,
                error_message=error.code,
            )
            raise KnowledgeIndexingFailedError("Knowledge indexing failed.") from error
        except _NoEnabledChunksError as error:
            await self._repository.fail_job(
                job_id,
                error_message="No chunks are enabled for embedding.",
            )
            raise KnowledgeIndexingFailedError("Knowledge indexing failed.") from error
        except EmbeddingProviderError as error:
            await self._repository.fail_job(
                job_id,
                error_message=error.code,
            )
            raise KnowledgeIndexingFailedError("Knowledge indexing failed.") from error
        except (QualityProviderError, _InvalidQualityBatchError) as error:
            await self._repository.fail_job(
                job_id,
                error_message="Knowledge indexing failed.",
            )
            raise KnowledgeIndexingFailedError("Knowledge indexing failed.") from error
        except KnowledgeIndexingFailedError:
            await self._repository.fail_job(
                job_id,
                error_message="Knowledge indexing failed.",
            )
            raise
        except Exception:
            await self._repository.fail_job(
                job_id,
                error_message="Knowledge indexing failed.",
            )
            raise
