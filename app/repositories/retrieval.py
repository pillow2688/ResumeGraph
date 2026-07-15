import math
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccessGrant,
    ChunkEmbedding,
    DocumentChunk,
    DocumentVersion,
    GrantProject,
    KnowledgeDocument,
    Project,
)


class DatabaseSessionProvider(Protocol):
    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


@dataclass(frozen=True, slots=True)
class RetrievalRecord:
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


class RetrievalRepositoryUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Retrieval persistence is unavailable.")


def _scope_filters(
    *,
    grant_id: UUID,
    project_ids: list[UUID],
    provider_name: str,
    model_name: str,
    dimensions: int,
) -> tuple[object, ...]:
    valid_grant = (
        select(AccessGrant.id)
        .where(
            AccessGrant.id == grant_id,
            AccessGrant.revoked_at.is_(None),
            AccessGrant.expires_at > func.now(),
        )
        .exists()
    )
    authorized_project = (
        select(GrantProject.project_id)
        .where(
            GrantProject.grant_id == grant_id,
            GrantProject.project_id == KnowledgeDocument.project_id,
        )
        .exists()
    )
    return (
        valid_grant,
        (
            (
                (KnowledgeDocument.document_scope == "profile")
                & KnowledgeDocument.project_id.is_(None)
            )
            | (
                (KnowledgeDocument.document_scope == "project")
                & KnowledgeDocument.project_id.in_(project_ids)
                & Project.id.in_(project_ids)
                & authorized_project
            )
        ),
        KnowledgeDocument.current_published_version_id.is_not(None),
        DocumentVersion.status == "published",
        DocumentChunk.enabled.is_(True),
        DocumentChunk.disabled_reason.is_(None),
        ChunkEmbedding.provider_name == provider_name,
        ChunkEmbedding.model_name == model_name,
        ChunkEmbedding.dimensions == dimensions,
        ChunkEmbedding.content_hash == DocumentChunk.content_hash,
    )


def _knowledge_join(statement: Select) -> Select:
    return (
        statement.select_from(KnowledgeDocument)
        .outerjoin(Project, Project.id == KnowledgeDocument.project_id)
        .join(
            DocumentVersion,
            DocumentVersion.id == KnowledgeDocument.current_published_version_id,
        )
        .join(
            DocumentChunk,
            DocumentChunk.document_version_id == DocumentVersion.id,
        )
        .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
    )


class RetrievalRepository:
    """Runs authorization and publication filtering inside PostgreSQL."""

    def __init__(self, database: DatabaseSessionProvider) -> None:
        self._database = database

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
    ) -> list[RetrievalRecord]:
        self._validate_arguments(
            query_embedding=query_embedding,
            project_ids=project_ids,
            provider_name=provider_name,
            model_name=model_name,
            dimensions=dimensions,
            top_k=top_k,
        )
        distance = ChunkEmbedding.embedding.cosine_distance(query_embedding)
        ranked = _knowledge_join(
            select(
                DocumentChunk.id.label("chunk_id"),
                DocumentChunk.content.label("content"),
                DocumentChunk.content_hash.label("content_hash"),
                KnowledgeDocument.document_scope.label("document_scope"),
                Project.id.label("project_id"),
                Project.name.label("project_name"),
                KnowledgeDocument.id.label("document_id"),
                KnowledgeDocument.title.label("document_title"),
                DocumentVersion.version_number.label("version_number"),
                DocumentChunk.heading_path.label("heading_path"),
                distance.label("distance"),
                func.row_number()
                .over(
                    partition_by=DocumentChunk.content_hash,
                    order_by=(distance.asc(), DocumentChunk.id.asc()),
                )
                .label("content_rank"),
            )
        ).where(
            *_scope_filters(
                grant_id=grant_id,
                project_ids=project_ids,
                provider_name=provider_name,
                model_name=model_name,
                dimensions=dimensions,
            )
        )
        ranked_subquery = ranked.subquery("ranked_evidence")
        statement = (
            select(
                ranked_subquery.c.chunk_id,
                ranked_subquery.c.content,
                ranked_subquery.c.content_hash,
                ranked_subquery.c.document_scope,
                ranked_subquery.c.project_id,
                ranked_subquery.c.project_name,
                ranked_subquery.c.document_id,
                ranked_subquery.c.document_title,
                ranked_subquery.c.version_number,
                ranked_subquery.c.heading_path,
                ranked_subquery.c.distance,
            )
            .where(ranked_subquery.c.content_rank == 1)
            .order_by(ranked_subquery.c.distance.asc(), ranked_subquery.c.chunk_id.asc())
            .limit(top_k)
        )

        try:
            async with self._database.session() as session:
                result = await session.execute(statement)
                return [
                    RetrievalRecord(
                        chunk_id=row["chunk_id"],
                        content=row["content"],
                        content_hash=row["content_hash"],
                        document_scope=row["document_scope"],
                        project_id=row["project_id"],
                        project_name=row["project_name"],
                        document_id=row["document_id"],
                        document_title=row["document_title"],
                        version_number=row["version_number"],
                        heading_path=tuple(row["heading_path"] or ()),
                        distance=float(row["distance"]),
                    )
                    for row in result.mappings().all()
                ]
        except (SQLAlchemyError, OSError) as error:
            raise RetrievalRepositoryUnavailableError from error

    async def revalidate(
        self,
        *,
        grant_id: UUID,
        project_ids: list[UUID],
        chunk_ids: list[UUID],
        provider_name: str,
        model_name: str,
        dimensions: int,
    ) -> set[UUID]:
        if not project_ids:
            raise ValueError("Retrieval project scope cannot be empty.")
        if not chunk_ids:
            return set()
        statement = _knowledge_join(select(DocumentChunk.id)).where(
            DocumentChunk.id.in_(chunk_ids),
            *_scope_filters(
                grant_id=grant_id,
                project_ids=project_ids,
                provider_name=provider_name,
                model_name=model_name,
                dimensions=dimensions,
            ),
        )
        try:
            async with self._database.session() as session:
                result = await session.execute(statement)
                return set(result.scalars().all())
        except (SQLAlchemyError, OSError) as error:
            raise RetrievalRepositoryUnavailableError from error

    @staticmethod
    def _validate_arguments(
        *,
        query_embedding: list[float],
        project_ids: list[UUID],
        provider_name: str,
        model_name: str,
        dimensions: int,
        top_k: int,
    ) -> None:
        if not project_ids:
            raise ValueError("Retrieval project scope cannot be empty.")
        if not provider_name.strip() or not model_name.strip():
            raise ValueError("Retrieval embedding identity cannot be empty.")
        if dimensions <= 0 or len(query_embedding) != dimensions:
            raise ValueError("Retrieval query embedding dimensions are invalid.")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in query_embedding
        ):
            raise ValueError("Retrieval query embedding values are invalid.")
        if top_k <= 0:
            raise ValueError("Retrieval top_k must be positive.")
