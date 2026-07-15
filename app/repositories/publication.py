import math
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChunkEmbedding, DocumentChunk, DocumentVersion, KnowledgeDocument
from app.repositories.ingestion import DocumentChunkRecord

EDITABLE_VERSION_STATUSES = {"ready_for_review", "indexing_failed", "ready_to_publish"}


class DatabaseSessionProvider(Protocol):
    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


class ChunkNotEditableRepositoryError(Exception):
    pass


class VersionNotPublishableRepositoryError(Exception):
    pass


class PublicationIntegrityRepositoryError(Exception):
    pass


class PublicationRepositoryUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Knowledge publication persistence is unavailable.")


@dataclass(frozen=True)
class PublicationStateRecord:
    document_id: UUID
    current_published_version_id: UUID | None
    document_scope: str = "project"
    project_id: UUID | None = None


def _chunk_record(chunk: DocumentChunk) -> DocumentChunkRecord:
    return DocumentChunkRecord(
        id=chunk.id,
        document_version_id=chunk.document_version_id,
        chunk_index=chunk.chunk_index,
        heading_path=tuple(chunk.heading_path),
        content=chunk.content,
        content_hash=chunk.content_hash,
        character_count=chunk.character_count,
        enabled=chunk.enabled,
        created_at=chunk.created_at,
        disabled_reason=chunk.disabled_reason,
        auto_indexable=chunk.auto_indexable,
        quality_issues=tuple(chunk.quality_issues or []),
        extracted_metadata=chunk.extracted_metadata,
        quality_checked_at=chunk.quality_checked_at,
        quality_model=chunk.quality_model,
        quality_reason=chunk.quality_reason,
    )


class PublicationRepository:
    def __init__(self, database: DatabaseSessionProvider) -> None:
        self._database = database

    async def set_chunk_enabled(
        self,
        chunk_id: UUID,
        *,
        enabled: bool,
    ) -> DocumentChunkRecord | None:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(DocumentChunk, DocumentVersion)
                    .join(
                        DocumentVersion,
                        DocumentVersion.id == DocumentChunk.document_version_id,
                    )
                    .where(DocumentChunk.id == chunk_id)
                    .with_for_update()
                )
                row = result.one_or_none()
                if row is None:
                    return None
                chunk, version = row
                if version.status not in EDITABLE_VERSION_STATUSES:
                    raise ChunkNotEditableRepositoryError
                if enabled and chunk.disabled_reason == "hard_block":
                    raise ChunkNotEditableRepositoryError
                if chunk.enabled == enabled:
                    return _chunk_record(chunk)

                chunk.enabled = enabled
                chunk.disabled_reason = None if enabled else "administrator"
                version.status = "ready_for_review"
                await session.commit()
                return _chunk_record(chunk)
        except ChunkNotEditableRepositoryError:
            raise
        except (SQLAlchemyError, OSError) as error:
            raise PublicationRepositoryUnavailableError from error

    async def publish_version(
        self,
        version_id: UUID,
        *,
        provider_name: str,
        model_name: str,
        dimensions: int,
    ) -> PublicationStateRecord | None:
        if not provider_name or not model_name or dimensions <= 0:
            raise ValueError("The active embedding identity is invalid.")
        try:
            async with self._database.session() as session:
                version_result = await session.execute(
                    select(DocumentVersion, KnowledgeDocument)
                    .join(
                        KnowledgeDocument,
                        KnowledgeDocument.id == DocumentVersion.document_id,
                    )
                    .where(DocumentVersion.id == version_id)
                    .with_for_update()
                )
                row = version_result.one_or_none()
                if row is None:
                    return None
                version, document = row
                if version.status != "ready_to_publish":
                    raise VersionNotPublishableRepositoryError

                chunk_result = await session.execute(
                    select(DocumentChunk)
                    .where(
                        DocumentChunk.document_version_id == version.id,
                        DocumentChunk.enabled.is_(True),
                    )
                    .with_for_update()
                )
                chunks = {chunk.id: chunk for chunk in chunk_result.scalars().all()}
                if not chunks:
                    raise PublicationIntegrityRepositoryError

                embedding_result = await session.execute(
                    select(ChunkEmbedding)
                    .where(
                        ChunkEmbedding.chunk_id.in_(chunks),
                        ChunkEmbedding.provider_name == provider_name,
                        ChunkEmbedding.model_name == model_name,
                        ChunkEmbedding.dimensions == dimensions,
                    )
                    .with_for_update()
                )
                embeddings = {
                    embedding.chunk_id: embedding for embedding in embedding_result.scalars().all()
                }
                if set(embeddings) != set(chunks):
                    raise PublicationIntegrityRepositoryError
                for chunk_id, chunk in chunks.items():
                    embedding = embeddings[chunk_id]
                    vector = embedding.embedding
                    if (
                        embedding.provider_name != provider_name
                        or embedding.model_name != model_name
                        or embedding.dimensions != dimensions
                        or embedding.content_hash != chunk.content_hash
                        or len(vector) != dimensions
                        or any(not math.isfinite(value) for value in vector)
                    ):
                        raise PublicationIntegrityRepositoryError

                old_version_id = document.current_published_version_id
                old_version = None
                if old_version_id is not None and old_version_id != version.id:
                    old_result = await session.execute(
                        select(DocumentVersion)
                        .where(DocumentVersion.id == old_version_id)
                        .with_for_update()
                    )
                    old_version = old_result.scalar_one_or_none()

                now = datetime.now(UTC)
                version.status = "published"
                if old_version is not None:
                    old_version.status = "superseded"
                document.current_published_version_id = version.id
                document.updated_at = now
                await session.commit()
                return PublicationStateRecord(
                    document_id=document.id,
                    current_published_version_id=version.id,
                    document_scope=document.document_scope,
                    project_id=document.project_id,
                )
        except (
            VersionNotPublishableRepositoryError,
            PublicationIntegrityRepositoryError,
        ):
            raise
        except (SQLAlchemyError, OSError) as error:
            raise PublicationRepositoryUnavailableError from error

    async def unpublish_document(
        self,
        document_id: UUID,
    ) -> PublicationStateRecord | None:
        try:
            async with self._database.session() as session:
                document_result = await session.execute(
                    select(KnowledgeDocument)
                    .where(KnowledgeDocument.id == document_id)
                    .with_for_update()
                )
                document = document_result.scalar_one_or_none()
                if document is None:
                    return None
                current_version_id = document.current_published_version_id
                if current_version_id is None:
                    return PublicationStateRecord(
                        document_id=document.id,
                        current_published_version_id=None,
                        document_scope=document.document_scope,
                        project_id=document.project_id,
                    )

                version_result = await session.execute(
                    select(DocumentVersion)
                    .where(DocumentVersion.id == current_version_id)
                    .with_for_update()
                )
                current_version = version_result.scalar_one_or_none()
                if current_version is not None:
                    current_version.status = "superseded"
                document.current_published_version_id = None
                document.updated_at = datetime.now(UTC)
                await session.commit()
                return PublicationStateRecord(
                    document_id=document.id,
                    current_published_version_id=None,
                    document_scope=document.document_scope,
                    project_id=document.project_id,
                )
        except (SQLAlchemyError, OSError) as error:
            raise PublicationRepositoryUnavailableError from error
