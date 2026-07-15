import asyncio
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.infrastructure.embedding import EmbeddingProvider, EmbeddingProviderError
from app.quality.rules import ChunkRuleInput, RuleConfig, validate_chunks
from app.repositories.deduplication import (
    DeduplicationCandidate,
    DeduplicationChange,
    DeduplicationEmbedding,
    DeduplicationRepositoryUnavailableError,
    DeduplicationScope,
    DeduplicationSnapshot,
)

EXACT_DUPLICATE_ISSUE: dict[str, object] = {
    "source": "deduplication",
    "code": "exact_duplicate",
    "severity": "hard_block",
}


class DeduplicationRepositoryBackend(Protocol):
    async def load_scope(
        self,
        scope: DeduplicationScope,
        *,
        provider_name: str,
        model_name: str,
        dimensions: int,
    ) -> DeduplicationSnapshot: ...

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
    ) -> bool: ...


class DeduplicationUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Knowledge deduplication is temporarily unavailable.")


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    canonical_count: int
    duplicate_count: int
    generated_embedding_count: int


def _without_exact_duplicate(
    issues: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    return tuple(issue for issue in issues if issue.get("code") != "exact_duplicate")


def _with_exact_duplicate(
    issues: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    cleaned = _without_exact_duplicate(issues)
    return cleaned + (EXACT_DUPLICATE_ISSUE.copy(),)


class DeduplicationService:
    def __init__(
        self,
        repository: DeduplicationRepositoryBackend,
        embedding_provider: EmbeddingProvider,
        *,
        dependency_timeout_seconds: float,
        max_snapshot_retries: int = 1,
        rule_config: RuleConfig | None = None,
    ) -> None:
        if dependency_timeout_seconds <= 0:
            raise ValueError("Dependency timeout must be positive.")
        if max_snapshot_retries < 0:
            raise ValueError("Snapshot retries cannot be negative.")
        self._repository = repository
        self._embedding_provider = embedding_provider
        self._dependency_timeout_seconds = dependency_timeout_seconds
        self._max_snapshot_retries = max_snapshot_retries
        self._rule_config = rule_config or RuleConfig()

    async def rebuild_profile_scope(self) -> DeduplicationResult:
        return await self._rebuild(DeduplicationScope(scope="profile"))

    async def rebuild_project_scope(self, project_id: UUID) -> DeduplicationResult:
        return await self._rebuild(DeduplicationScope(scope="project", project_id=project_id))

    async def _rebuild(self, scope: DeduplicationScope) -> DeduplicationResult:
        for attempt in range(self._max_snapshot_retries + 1):
            try:
                snapshot = await asyncio.wait_for(
                    self._repository.load_scope(
                        scope,
                        provider_name=self._embedding_provider.provider_name,
                        model_name=self._embedding_provider.model_name,
                        dimensions=self._embedding_provider.dimensions,
                    ),
                    timeout=self._dependency_timeout_seconds,
                )
                changes, embeddings, result = await self._build_plan(snapshot)
                applied = await asyncio.wait_for(
                    self._repository.apply_scope(
                        scope,
                        expected_revision=snapshot.revision,
                        changes=changes,
                        embeddings=embeddings,
                        provider_name=self._embedding_provider.provider_name,
                        model_name=self._embedding_provider.model_name,
                        dimensions=self._embedding_provider.dimensions,
                    ),
                    timeout=self._dependency_timeout_seconds,
                )
            except (
                TimeoutError,
                DeduplicationRepositoryUnavailableError,
                EmbeddingProviderError,
            ) as error:
                raise DeduplicationUnavailableError from error
            if applied:
                return result
            if attempt == self._max_snapshot_retries:
                break
        raise DeduplicationUnavailableError

    async def _build_plan(
        self,
        snapshot: DeduplicationSnapshot,
    ) -> tuple[
        list[DeduplicationChange],
        list[DeduplicationEmbedding],
        DeduplicationResult,
    ]:
        eligible = [
            item
            for item in snapshot.candidates
            if item.enabled or item.disabled_reason == "exact_duplicate"
        ]
        protected = [item for item in snapshot.candidates if item not in eligible]
        groups: dict[str, list[DeduplicationCandidate]] = defaultdict(list)
        for item in eligible:
            groups[item.content_hash].append(item)

        changes: list[DeduplicationChange] = [
            DeduplicationChange(
                chunk_id=item.chunk_id,
                content_hash=item.content_hash,
                enabled=item.enabled,
                disabled_reason=item.disabled_reason,
                quality_issues=item.quality_issues,
            )
            for item in protected
        ]
        embeddings: list[DeduplicationEmbedding] = []
        provider_requests: list[DeduplicationCandidate] = []
        canonical_count = 0
        duplicate_count = 0

        for items in groups.values():
            ordered = sorted(items, key=lambda item: (item.created_at, str(item.chunk_id)))
            canonical = ordered[0]
            canonical_count += 1
            changes.append(
                DeduplicationChange(
                    chunk_id=canonical.chunk_id,
                    content_hash=canonical.content_hash,
                    enabled=True,
                    disabled_reason=None,
                    quality_issues=_without_exact_duplicate(canonical.quality_issues),
                )
            )
            if canonical.embedding is None:
                donor = next(
                    (item.embedding for item in ordered if item.embedding is not None),
                    None,
                )
                if donor is not None:
                    embeddings.append(
                        DeduplicationEmbedding(
                            chunk_id=canonical.chunk_id,
                            content_hash=canonical.content_hash,
                            embedding=donor,
                        )
                    )
                else:
                    provider_requests.append(canonical)

            for duplicate in ordered[1:]:
                duplicate_count += 1
                changes.append(
                    DeduplicationChange(
                        chunk_id=duplicate.chunk_id,
                        content_hash=duplicate.content_hash,
                        enabled=False,
                        disabled_reason="exact_duplicate",
                        quality_issues=_with_exact_duplicate(duplicate.quality_issues),
                    )
                )

        generated_count = 0
        if provider_requests:
            payloads: list[str] = []
            for item in provider_requests:
                rule_result = validate_chunks(
                    [
                        ChunkRuleInput(
                            chunk_id=item.chunk_id,
                            chunk_index=0,
                            content=item.content,
                            content_hash=item.content_hash,
                        )
                    ],
                    config=self._rule_config,
                )[0]
                if rule_result.hard_blocked or rule_result.redacted_content is None:
                    raise DeduplicationUnavailableError
                payloads.append(rule_result.redacted_content)
            vectors = await self._embedding_provider.embed_texts(payloads)
            if len(vectors) != len(provider_requests):
                raise DeduplicationUnavailableError
            for item, vector in zip(provider_requests, vectors, strict=True):
                if len(vector) != self._embedding_provider.dimensions or any(
                    not math.isfinite(value) for value in vector
                ):
                    raise DeduplicationUnavailableError
                embeddings.append(
                    DeduplicationEmbedding(
                        chunk_id=item.chunk_id,
                        content_hash=item.content_hash,
                        embedding=tuple(float(value) for value in vector),
                    )
                )
                generated_count += 1

        return (
            changes,
            embeddings,
            DeduplicationResult(
                canonical_count=canonical_count,
                duplicate_count=duplicate_count,
                generated_embedding_count=generated_count,
            ),
        )
