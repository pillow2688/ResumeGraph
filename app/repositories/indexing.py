import math
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChunkEmbedding,
    DocumentChunk,
    DocumentVersion,
    IngestionJob,
    KnowledgeDocument,
)
from app.repositories.ingestion import CreateIngestionJobResult, IngestionJobRecord


class DatabaseSessionProvider(Protocol):
    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


@dataclass(frozen=True, slots=True)
class IndexingChunk:
    id: UUID
    chunk_index: int
    content: str
    content_hash: str
    enabled: bool
    auto_indexable: bool | None


@dataclass(frozen=True, slots=True)
class IndexingWorkItem:
    job_id: UUID
    document_version_id: UUID
    chunks: tuple[IndexingChunk, ...]


@dataclass(frozen=True, slots=True)
class ChunkQualityUpdate:
    chunk_id: UUID
    auto_indexable: bool
    enabled: bool | None
    quality_issues: tuple[dict[str, str], ...]
    extracted_metadata: dict[str, object]
    quality_checked_at: datetime
    quality_model: str
    quality_reason: str


@dataclass(frozen=True, slots=True)
class ChunkEmbeddingToSave:
    chunk_id: UUID
    embedding: tuple[float, ...]
    provider_name: str
    model_name: str
    dimensions: int
    content_hash: str


class IndexingVersionNotProcessableRepositoryError(Exception):
    pass


class IndexingRepositoryUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Knowledge indexing persistence is unavailable.")


def _job_record(
    job: IngestionJob,
    version: DocumentVersion,
    document: KnowledgeDocument,
) -> IngestionJobRecord:
    return IngestionJobRecord(
        id=job.id,
        document_version_id=job.document_version_id,
        document_id=version.document_id,
        document_title=document.title,
        version_number=version.version_number,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        job_type=job.job_type,
    )


class IndexingRepository:
    def __init__(self, database: DatabaseSessionProvider) -> None:
        self._database = database

    async def create_job(self, version_id: UUID) -> CreateIngestionJobResult | None:
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

                active_result = await session.execute(
                    select(IngestionJob)
                    .where(
                        IngestionJob.document_version_id == version_id,
                        IngestionJob.job_type == "knowledge_indexing",
                        IngestionJob.status.in_(("pending", "processing")),
                    )
                    .order_by(IngestionJob.created_at.desc())
                    .limit(1)
                )
                active_job = active_result.scalar_one_or_none()
                if active_job is not None:
                    return CreateIngestionJobResult(
                        record=_job_record(active_job, version, document),
                        created=False,
                    )
                if version.status not in {"ready_for_review", "indexing_failed"}:
                    raise IndexingVersionNotProcessableRepositoryError

                job = IngestionJob(
                    id=uuid4(),
                    document_version_id=version_id,
                    job_type="knowledge_indexing",
                    status="pending",
                    stage="rule_check",
                    progress=0,
                )
                version.status = "indexing"
                session.add(job)
                await session.flush()
                await session.refresh(job)
                await session.commit()
                return CreateIngestionJobResult(
                    record=_job_record(job, version, document),
                    created=True,
                )
        except IndexingVersionNotProcessableRepositoryError:
            raise
        except (SQLAlchemyError, OSError) as error:
            raise IndexingRepositoryUnavailableError from error

    async def mark_enqueue_failed(self, job_id: UUID, *, error_message: str) -> None:
        await self._fail_active_job(job_id, error_message=error_message)

    async def begin_job(self, job_id: UUID) -> IndexingWorkItem | None:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(IngestionJob, DocumentVersion)
                    .join(
                        DocumentVersion,
                        DocumentVersion.id == IngestionJob.document_version_id,
                    )
                    .where(IngestionJob.id == job_id)
                    .with_for_update()
                )
                row = result.one_or_none()
                if row is None:
                    return None
                job, version = row
                if job.job_type != "knowledge_indexing" or job.status not in {
                    "pending",
                    "processing",
                }:
                    return None

                chunk_result = await session.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_version_id == version.id)
                    .order_by(DocumentChunk.chunk_index.asc())
                )
                chunks = tuple(
                    IndexingChunk(
                        id=chunk.id,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        content_hash=chunk.content_hash,
                        enabled=chunk.enabled,
                        auto_indexable=chunk.auto_indexable,
                    )
                    for chunk in chunk_result.scalars().all()
                )
                now = datetime.now(UTC)
                job.status = "processing"
                job.stage = "rule_check"
                job.progress = 5
                job.error_message = None
                if job.started_at is None:
                    job.started_at = now
                version.status = "indexing"
                await session.commit()
                return IndexingWorkItem(
                    job_id=job.id,
                    document_version_id=version.id,
                    chunks=chunks,
                )
        except (SQLAlchemyError, OSError) as error:
            raise IndexingRepositoryUnavailableError from error

    async def set_stage(self, job_id: UUID, *, stage: str, progress: int) -> bool:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(IngestionJob).where(IngestionJob.id == job_id).with_for_update()
                )
                job = result.scalar_one_or_none()
                if (
                    job is None
                    or job.job_type != "knowledge_indexing"
                    or job.status != "processing"
                ):
                    return False
                job.stage = stage
                job.progress = progress
                await session.commit()
                return True
        except (SQLAlchemyError, OSError) as error:
            raise IndexingRepositoryUnavailableError from error

    async def save_quality_results(
        self,
        job_id: UUID,
        *,
        updates: list[ChunkQualityUpdate],
    ) -> bool:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(IngestionJob, DocumentVersion)
                    .join(
                        DocumentVersion,
                        DocumentVersion.id == IngestionJob.document_version_id,
                    )
                    .where(IngestionJob.id == job_id)
                    .with_for_update()
                )
                row = result.one_or_none()
                if row is None:
                    return False
                job, version = row
                if job.job_type != "knowledge_indexing" or job.status != "processing":
                    return False

                chunk_result = await session.execute(
                    select(DocumentChunk).where(DocumentChunk.document_version_id == version.id)
                )
                chunks = {chunk.id: chunk for chunk in chunk_result.scalars().all()}
                if set(chunks) != {update.chunk_id for update in updates}:
                    raise ValueError(
                        "Quality updates must match the current document-version chunks."
                    )
                for update in updates:
                    chunk = chunks[update.chunk_id]
                    chunk.auto_indexable = update.auto_indexable
                    if update.enabled is not None:
                        chunk.enabled = update.enabled
                    chunk.quality_issues = list(update.quality_issues)
                    chunk.extracted_metadata = update.extracted_metadata
                    chunk.quality_checked_at = update.quality_checked_at
                    chunk.quality_model = update.quality_model
                    chunk.quality_reason = update.quality_reason
                await session.commit()
                return True
        except (SQLAlchemyError, OSError) as error:
            raise IndexingRepositoryUnavailableError from error

    async def save_embeddings(
        self,
        job_id: UUID,
        *,
        embeddings: list[ChunkEmbeddingToSave],
    ) -> bool:
        if not embeddings:
            raise ValueError("At least one enabled chunk embedding is required.")
        provider_names = {item.provider_name for item in embeddings}
        model_names = {item.model_name for item in embeddings}
        dimensions = {item.dimensions for item in embeddings}
        if len(provider_names) != 1 or len(model_names) != 1 or len(dimensions) != 1:
            raise ValueError("An embedding save batch must use one provider, model, and dimension.")

        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(IngestionJob, DocumentVersion)
                    .join(
                        DocumentVersion,
                        DocumentVersion.id == IngestionJob.document_version_id,
                    )
                    .where(IngestionJob.id == job_id)
                    .with_for_update()
                )
                row = result.one_or_none()
                if row is None:
                    return False
                job, version = row
                if job.job_type != "knowledge_indexing" or job.status != "processing":
                    return False

                chunk_ids = {item.chunk_id for item in embeddings}
                chunk_result = await session.execute(
                    select(DocumentChunk).where(
                        DocumentChunk.document_version_id == version.id,
                        DocumentChunk.id.in_(chunk_ids),
                    )
                )
                chunks = {chunk.id: chunk for chunk in chunk_result.scalars().all()}
                if set(chunks) != chunk_ids:
                    raise ValueError("Embedding chunks must belong to the current version.")
                for item in embeddings:
                    chunk = chunks[item.chunk_id]
                    if not chunk.enabled:
                        raise ValueError("Disabled chunks cannot receive embeddings.")
                    if item.content_hash != chunk.content_hash:
                        raise ValueError("Embedding content hash must match the chunk.")
                    if item.dimensions <= 0 or len(item.embedding) != item.dimensions:
                        raise ValueError("Embedding dimensions are invalid.")
                    if any(not math.isfinite(value) for value in item.embedding):
                        raise ValueError("Embedding values must be finite.")

                provider_name = embeddings[0].provider_name
                model_name = embeddings[0].model_name
                dimension = embeddings[0].dimensions
                existing_result = await session.execute(
                    select(ChunkEmbedding).where(
                        ChunkEmbedding.chunk_id.in_(chunk_ids),
                        ChunkEmbedding.provider_name == provider_name,
                        ChunkEmbedding.model_name == model_name,
                        ChunkEmbedding.dimensions == dimension,
                    )
                )
                existing = {
                    (
                        item.chunk_id,
                        item.provider_name,
                        item.model_name,
                        item.dimensions,
                    ): item
                    for item in existing_result.scalars().all()
                }
                for item in embeddings:
                    row_key = (
                        item.chunk_id,
                        item.provider_name,
                        item.model_name,
                        item.dimensions,
                    )
                    embedding_row = existing.get(row_key)
                    if embedding_row is None:
                        embedding_row = ChunkEmbedding(
                            id=uuid4(),
                            chunk_id=item.chunk_id,
                            embedding=list(item.embedding),
                            provider_name=item.provider_name,
                            model_name=item.model_name,
                            dimensions=item.dimensions,
                            content_hash=item.content_hash,
                        )
                        session.add(embedding_row)
                    else:
                        embedding_row.embedding = list(item.embedding)
                        embedding_row.dimensions = item.dimensions
                        embedding_row.content_hash = item.content_hash
                await session.commit()
                return True
        except (SQLAlchemyError, OSError) as error:
            raise IndexingRepositoryUnavailableError from error

    async def complete_job(
        self,
        job_id: UUID,
        *,
        provider_name: str,
        model_name: str,
        dimensions: int,
    ) -> bool:
        if not provider_name:
            raise ValueError("Embedding provider name cannot be empty.")
        if not model_name:
            raise ValueError("Embedding model name cannot be empty.")
        if dimensions <= 0:
            raise ValueError("Embedding dimensions must be positive.")
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(IngestionJob, DocumentVersion)
                    .join(
                        DocumentVersion,
                        DocumentVersion.id == IngestionJob.document_version_id,
                    )
                    .where(IngestionJob.id == job_id)
                    .with_for_update()
                )
                row = result.one_or_none()
                if row is None:
                    return False
                job, version = row
                if job.job_type != "knowledge_indexing" or job.status != "processing":
                    return False

                chunk_result = await session.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_version_id == version.id)
                    .with_for_update()
                )
                chunks = {
                    chunk.id: chunk for chunk in chunk_result.scalars().all() if chunk.enabled
                }
                if not chunks:
                    return False

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
                    return False
                for chunk_id, chunk in chunks.items():
                    embedding = embeddings[chunk_id]
                    if (
                        embedding.provider_name != provider_name
                        or embedding.model_name != model_name
                        or embedding.content_hash != chunk.content_hash
                        or embedding.dimensions != dimensions
                        or len(embedding.embedding) != dimensions
                        or any(not math.isfinite(value) for value in embedding.embedding)
                    ):
                        return False

                job.status = "completed"
                job.stage = "saving"
                job.progress = 100
                job.error_message = None
                job.finished_at = datetime.now(UTC)
                version.status = "ready_to_publish"
                await session.commit()
                return True
        except (SQLAlchemyError, OSError) as error:
            raise IndexingRepositoryUnavailableError from error

    async def fail_job(self, job_id: UUID, *, error_message: str) -> None:
        await self._fail_active_job(job_id, error_message=error_message)

    async def _fail_active_job(self, job_id: UUID, *, error_message: str) -> None:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(IngestionJob, DocumentVersion)
                    .join(
                        DocumentVersion,
                        DocumentVersion.id == IngestionJob.document_version_id,
                    )
                    .where(IngestionJob.id == job_id)
                    .with_for_update()
                )
                row = result.one_or_none()
                if row is None:
                    return
                job, version = row
                if job.job_type != "knowledge_indexing" or job.status not in {
                    "pending",
                    "processing",
                }:
                    return
                job.status = "failed"
                job.error_message = error_message
                job.finished_at = datetime.now(UTC)
                version.status = "indexing_failed"
                await session.commit()
        except (SQLAlchemyError, OSError) as error:
            raise IndexingRepositoryUnavailableError from error
