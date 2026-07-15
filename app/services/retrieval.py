import asyncio
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from app.infrastructure.embedding import EmbeddingProvider, EmbeddingProviderError
from app.repositories.retrieval import RetrievalRecord, RetrievalRepositoryUnavailableError


class RetrievalRepositoryBackend(Protocol):
    async def search(
        self,
        *,
        grant_id: UUID,
        query_embedding: list[float],
        project_ids: list[UUID],
        provider_name: str,
        model_name: str,
        dimensions: int,
        top_k: int,
    ) -> list[RetrievalRecord]: ...

    async def revalidate(
        self,
        *,
        grant_id: UUID,
        project_ids: list[UUID],
        chunk_ids: list[UUID],
        provider_name: str,
        model_name: str,
        dimensions: int,
    ) -> set[UUID]: ...


@dataclass(frozen=True, slots=True)
class Evidence:
    citation_handle: str
    chunk_id: UUID
    content: str
    content_hash: str
    document_scope: Literal["profile", "project"]
    project_id: UUID | None
    project_name: str | None
    document_id: UUID
    document_title: str
    version_number: int
    heading_path: tuple[str, ...]
    distance: float


class EmptyProjectScopeError(Exception):
    pass


class RetrievalUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Retrieval is temporarily unavailable.")


class RetrievalService:
    def __init__(
        self,
        repository: RetrievalRepositoryBackend,
        embedding_provider: EmbeddingProvider,
        *,
        top_k: int,
        max_context_characters: int,
        dependency_timeout_seconds: float,
    ) -> None:
        if top_k <= 0:
            raise ValueError("Retrieval top_k must be positive.")
        if max_context_characters <= 0:
            raise ValueError("Retrieval context budget must be positive.")
        if dependency_timeout_seconds <= 0:
            raise ValueError("Retrieval timeout must be positive.")
        self._repository = repository
        self._embedding_provider = embedding_provider
        self._top_k = top_k
        self._max_context_characters = max_context_characters
        self._dependency_timeout_seconds = dependency_timeout_seconds

    @staticmethod
    def resolve_project_scope(
        allowed_project_ids: list[UUID],
        requested_project_ids: list[UUID] | None,
    ) -> list[UUID]:
        allowed = list(dict.fromkeys(allowed_project_ids))
        if requested_project_ids is None:
            effective = allowed
        else:
            requested = set(requested_project_ids)
            effective = [project_id for project_id in allowed if project_id in requested]
        if not effective:
            raise EmptyProjectScopeError
        return effective

    async def retrieve(
        self,
        *,
        query: str,
        grant_id: UUID,
        project_ids: list[UUID],
    ) -> list[Evidence]:
        if not query.strip():
            raise ValueError("Retrieval query cannot be empty.")
        try:
            query_embedding = await asyncio.wait_for(
                self._embedding_provider.embed_query(query),
                timeout=self._dependency_timeout_seconds,
            )
            records = await asyncio.wait_for(
                self._repository.search(
                    grant_id=grant_id,
                    query_embedding=query_embedding,
                    project_ids=project_ids,
                    provider_name=self._embedding_provider.provider_name,
                    model_name=self._embedding_provider.model_name,
                    dimensions=self._embedding_provider.dimensions,
                    top_k=self._top_k,
                ),
                timeout=self._dependency_timeout_seconds,
            )
        except (TimeoutError, EmbeddingProviderError, RetrievalRepositoryUnavailableError) as error:
            raise RetrievalUnavailableError from error

        evidence: list[Evidence] = []
        seen_hashes: set[str] = set()
        used_characters = 0
        for record in records:
            if record.content_hash in seen_hashes:
                continue
            next_size = used_characters + len(record.content)
            if next_size > self._max_context_characters:
                continue
            seen_hashes.add(record.content_hash)
            used_characters = next_size
            evidence.append(
                Evidence(
                    citation_handle=f"evidence_{len(evidence) + 1}",
                    chunk_id=record.chunk_id,
                    content=record.content,
                    content_hash=record.content_hash,
                    document_scope=record.document_scope,
                    project_id=record.project_id,
                    project_name=record.project_name,
                    document_id=record.document_id,
                    document_title=record.document_title,
                    version_number=record.version_number,
                    heading_path=record.heading_path,
                    distance=record.distance,
                )
            )
        return evidence

    async def revalidate(
        self,
        *,
        grant_id: UUID,
        project_ids: list[UUID],
        evidence: list[Evidence],
    ) -> set[str]:
        if not evidence:
            return set()
        try:
            valid_chunk_ids = await asyncio.wait_for(
                self._repository.revalidate(
                    grant_id=grant_id,
                    project_ids=project_ids,
                    chunk_ids=[item.chunk_id for item in evidence],
                    provider_name=self._embedding_provider.provider_name,
                    model_name=self._embedding_provider.model_name,
                    dimensions=self._embedding_provider.dimensions,
                ),
                timeout=self._dependency_timeout_seconds,
            )
        except (TimeoutError, RetrievalRepositoryUnavailableError) as error:
            raise RetrievalUnavailableError from error
        return {item.citation_handle for item in evidence if item.chunk_id in valid_chunk_ids}
