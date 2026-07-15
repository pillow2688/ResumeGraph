from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChunkEmbedding,
    DocumentChunk,
    DocumentVersion,
    KnowledgeDocument,
)


class DatabaseSessionProvider(Protocol):
    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


@dataclass(frozen=True, slots=True)
class DeduplicationScope:
    scope: Literal["profile", "project"]
    project_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.scope == "profile" and self.project_id is not None:
            raise ValueError("Profile deduplication cannot have a project ID.")
        if self.scope == "project" and self.project_id is None:
            raise ValueError("Project deduplication requires a project ID.")


@dataclass(frozen=True, slots=True)
class DeduplicationCandidate:
    chunk_id: UUID
    content: str
    content_hash: str
    created_at: datetime
    enabled: bool
    disabled_reason: str | None
    quality_issues: tuple[dict[str, object], ...]
    embedding: tuple[float, ...] | None


@dataclass(frozen=True, slots=True)
class DeduplicationSnapshot:
    revision: tuple[tuple[UUID, UUID], ...]
    candidates: tuple[DeduplicationCandidate, ...]


@dataclass(frozen=True, slots=True)
class DeduplicationChange:
    chunk_id: UUID
    content_hash: str
    enabled: bool
    disabled_reason: str | None
    quality_issues: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class DeduplicationEmbedding:
    chunk_id: UUID
    content_hash: str
    embedding: tuple[float, ...]


class DeduplicationRepositoryUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Deduplication persistence is unavailable.")


def _scope_filters(scope: DeduplicationScope) -> tuple[object, ...]:
    if scope.scope == "profile":
        return (KnowledgeDocument.document_scope == "profile",)
    return (
        KnowledgeDocument.document_scope == "project",
        KnowledgeDocument.project_id == scope.project_id,
    )


def _scope_select(
    scope: DeduplicationScope,
    *,
    provider_name: str,
    model_name: str,
    dimensions: int,
):
    return (
        select(
            KnowledgeDocument.id,
            KnowledgeDocument.current_published_version_id,
            DocumentChunk.id,
            DocumentChunk.content,
            DocumentChunk.content_hash,
            DocumentChunk.created_at,
            DocumentChunk.enabled,
            DocumentChunk.disabled_reason,
            DocumentChunk.quality_issues,
            ChunkEmbedding.embedding,
        )
        .join(
            DocumentVersion,
            KnowledgeDocument.current_published_version_id == DocumentVersion.id,
        )
        .join(
            DocumentChunk,
            DocumentChunk.document_version_id == DocumentVersion.id,
        )
        .outerjoin(
            ChunkEmbedding,
            and_(
                ChunkEmbedding.chunk_id == DocumentChunk.id,
                ChunkEmbedding.provider_name == provider_name,
                ChunkEmbedding.model_name == model_name,
                ChunkEmbedding.dimensions == dimensions,
                ChunkEmbedding.content_hash == DocumentChunk.content_hash,
            ),
        )
        .where(
            *_scope_filters(scope),
            DocumentVersion.status == "published",
            or_(
                DocumentChunk.enabled.is_(True),
                DocumentChunk.disabled_reason == "exact_duplicate",
            ),
        )
        .order_by(
            DocumentChunk.content_hash.asc(),
            DocumentChunk.created_at.asc(),
            DocumentChunk.id.asc(),
        )
    )


def _revision_select(scope: DeduplicationScope):
    return (
        select(
            KnowledgeDocument.id,
            KnowledgeDocument.current_published_version_id,
        )
        .join(
            DocumentVersion,
            KnowledgeDocument.current_published_version_id == DocumentVersion.id,
        )
        .where(
            *_scope_filters(scope),
            KnowledgeDocument.current_published_version_id.is_not(None),
            DocumentVersion.status == "published",
        )
        .order_by(KnowledgeDocument.id.asc())
    )


class DeduplicationRepository:
    def __init__(self, database: DatabaseSessionProvider) -> None:
        self._database = database

    async def load_scope(
        self,
        scope: DeduplicationScope,
        *,
        provider_name: str,
        model_name: str,
        dimensions: int,
    ) -> DeduplicationSnapshot:
        if not provider_name or not model_name or dimensions <= 0:
            raise ValueError("The active embedding identity is invalid.")
        try:
            async with self._database.session() as session:
                revision_result = await session.execute(_revision_select(scope))
                result = await session.execute(
                    _scope_select(
                        scope,
                        provider_name=provider_name,
                        model_name=model_name,
                        dimensions=dimensions,
                    )
                )
                revision = {(row[0], row[1]) for row in revision_result.all() if row[1] is not None}
                candidates: list[DeduplicationCandidate] = []
                for row in result.all():
                    values = tuple(row)
                    version_id = values[1]
                    if version_id is None:
                        continue
                    candidates.append(
                        DeduplicationCandidate(
                            chunk_id=values[2],
                            content=values[3],
                            content_hash=values[4],
                            created_at=values[5],
                            enabled=values[6],
                            disabled_reason=values[7],
                            quality_issues=tuple(values[8] or []),
                            embedding=(
                                tuple(float(value) for value in values[9])
                                if values[9] is not None
                                else None
                            ),
                        )
                    )
                return DeduplicationSnapshot(
                    revision=tuple(sorted(revision, key=lambda item: (str(item[0]), str(item[1])))),
                    candidates=tuple(candidates),
                )
        except (SQLAlchemyError, OSError) as error:
            raise DeduplicationRepositoryUnavailableError from error

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
        if not provider_name or not model_name or dimensions <= 0:
            raise ValueError("The active embedding identity is invalid.")
        try:
            async with self._database.session() as session:
                document_result = await session.execute(_revision_select(scope).with_for_update())
                current_revision = tuple(
                    sorted(
                        ((row[0], row[1]) for row in document_result.all() if row[1] is not None),
                        key=lambda item: (str(item[0]), str(item[1])),
                    )
                )
                if current_revision != expected_revision:
                    return False

                change_by_id = {item.chunk_id: item for item in changes}
                if len(change_by_id) != len(changes):
                    raise ValueError("Deduplication changes must have unique chunk IDs.")
                chunk_result = await session.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.id.in_(change_by_id))
                    .with_for_update()
                )
                chunks = {item.id: item for item in chunk_result.scalars().all()}
                if set(chunks) != set(change_by_id):
                    return False
                for chunk_id, change in change_by_id.items():
                    chunk = chunks[chunk_id]
                    if chunk.content_hash != change.content_hash:
                        return False
                    chunk.enabled = change.enabled
                    chunk.disabled_reason = change.disabled_reason
                    chunk.quality_issues = list(change.quality_issues)

                disabled_ids = {item.chunk_id for item in changes if not item.enabled}
                if disabled_ids:
                    await session.execute(
                        delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id.in_(disabled_ids))
                    )

                embedding_by_id = {item.chunk_id: item for item in embeddings}
                if len(embedding_by_id) != len(embeddings):
                    raise ValueError("Deduplication embeddings must have unique chunk IDs.")
                if embedding_by_id:
                    existing_result = await session.execute(
                        select(ChunkEmbedding).where(
                            ChunkEmbedding.chunk_id.in_(embedding_by_id),
                            ChunkEmbedding.provider_name == provider_name,
                            ChunkEmbedding.model_name == model_name,
                            ChunkEmbedding.dimensions == dimensions,
                        )
                    )
                    existing = {item.chunk_id: item for item in existing_result.scalars().all()}
                    for chunk_id, item in embedding_by_id.items():
                        change = change_by_id[chunk_id]
                        if not change.enabled or item.content_hash != change.content_hash:
                            raise ValueError("Only canonical chunks can receive embeddings.")
                        row = existing.get(chunk_id)
                        if row is None:
                            session.add(
                                ChunkEmbedding(
                                    id=uuid4(),
                                    chunk_id=chunk_id,
                                    embedding=list(item.embedding),
                                    provider_name=provider_name,
                                    model_name=model_name,
                                    dimensions=dimensions,
                                    content_hash=item.content_hash,
                                )
                            )
                        else:
                            row.embedding = list(item.embedding)
                            row.content_hash = item.content_hash
                await session.commit()
                return True
        except (SQLAlchemyError, OSError) as error:
            raise DeduplicationRepositoryUnavailableError from error
