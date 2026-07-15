from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentChunk, DocumentVersion, IngestionJob, KnowledgeDocument


class DatabaseSessionProvider(Protocol):
    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


@dataclass(frozen=True)
class IngestionJobRecord:
    id: UUID
    document_version_id: UUID
    document_id: UUID
    document_title: str
    version_number: int
    status: str
    stage: str
    progress: int
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    job_type: str = "document_processing"


@dataclass(frozen=True)
class DocumentChunkRecord:
    id: UUID
    document_version_id: UUID
    chunk_index: int
    heading_path: tuple[str, ...]
    content: str
    content_hash: str
    character_count: int
    enabled: bool
    created_at: datetime
    auto_indexable: bool | None = None
    quality_issues: tuple[dict[str, object], ...] = ()
    extracted_metadata: dict[str, object] | None = None
    quality_checked_at: datetime | None = None
    quality_model: str | None = None
    quality_reason: str | None = None


@dataclass(frozen=True)
class CreateIngestionJobResult:
    record: IngestionJobRecord
    created: bool


@dataclass(frozen=True)
class IngestionWorkItem:
    job_id: UUID
    document_version_id: UUID
    raw_content: str


@dataclass(frozen=True)
class ChunkToSave:
    chunk_index: int
    heading_path: tuple[str, ...]
    content: str
    content_hash: str
    character_count: int
    enabled: bool = True


class DocumentVersionNotProcessableRepositoryError(Exception):
    pass


class IngestionRepositoryUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Document processing persistence is unavailable.")


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
        auto_indexable=chunk.auto_indexable,
        quality_issues=tuple(chunk.quality_issues),
        extracted_metadata=chunk.extracted_metadata,
        quality_checked_at=chunk.quality_checked_at,
        quality_model=chunk.quality_model,
        quality_reason=chunk.quality_reason,
    )


class IngestionRepository:
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
                if version.status not in {"draft", "processing"}:
                    raise DocumentVersionNotProcessableRepositoryError

                active_result = await session.execute(
                    select(IngestionJob)
                    .where(
                        IngestionJob.document_version_id == version_id,
                        IngestionJob.job_type == "document_processing",
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
                if version.status != "draft":
                    raise DocumentVersionNotProcessableRepositoryError

                job = IngestionJob(
                    id=uuid4(),
                    document_version_id=version_id,
                    job_type="document_processing",
                    status="pending",
                    stage="reading",
                    progress=0,
                )
                version.status = "processing"
                session.add(job)
                await session.flush()
                await session.refresh(job)
                await session.commit()
                return CreateIngestionJobResult(
                    record=_job_record(job, version, document),
                    created=True,
                )
        except DocumentVersionNotProcessableRepositoryError:
            raise
        except (SQLAlchemyError, OSError) as error:
            raise IngestionRepositoryUnavailableError from error

    async def mark_enqueue_failed(self, job_id: UUID, *, error_message: str) -> None:
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
                if job.job_type != "document_processing" or job.status not in {
                    "pending",
                    "processing",
                }:
                    return
                job.status = "failed"
                job.error_message = error_message
                job.finished_at = datetime.now(UTC)
                version.status = "draft"
                await session.commit()
        except (SQLAlchemyError, OSError) as error:
            raise IngestionRepositoryUnavailableError from error

    async def get_job(self, job_id: UUID) -> IngestionJobRecord | None:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(IngestionJob, DocumentVersion, KnowledgeDocument)
                    .join(
                        DocumentVersion,
                        DocumentVersion.id == IngestionJob.document_version_id,
                    )
                    .join(
                        KnowledgeDocument,
                        KnowledgeDocument.id == DocumentVersion.document_id,
                    )
                    .where(IngestionJob.id == job_id)
                )
                row = result.one_or_none()
                if row is None:
                    return None
                return _job_record(*row)
        except (SQLAlchemyError, OSError) as error:
            raise IngestionRepositoryUnavailableError from error

    async def list_chunks(self, version_id: UUID) -> list[DocumentChunkRecord] | None:
        try:
            async with self._database.session() as session:
                version_result = await session.execute(
                    select(DocumentVersion.id).where(DocumentVersion.id == version_id)
                )
                if version_result.scalar_one_or_none() is None:
                    return None
                result = await session.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_version_id == version_id)
                    .order_by(DocumentChunk.chunk_index.asc())
                )
                return [_chunk_record(chunk) for chunk in result.scalars().all()]
        except (SQLAlchemyError, OSError) as error:
            raise IngestionRepositoryUnavailableError from error

    async def begin_job(self, job_id: UUID) -> IngestionWorkItem | None:
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
                if job.job_type != "document_processing" or job.status not in {
                    "pending",
                    "processing",
                }:
                    return None
                now = datetime.now(UTC)
                job.status = "processing"
                job.stage = "reading"
                job.progress = 5
                job.error_message = None
                if job.started_at is None:
                    job.started_at = now
                version.status = "processing"
                await session.commit()
                return IngestionWorkItem(
                    job_id=job.id,
                    document_version_id=version.id,
                    raw_content=version.raw_content,
                )
        except (SQLAlchemyError, OSError) as error:
            raise IngestionRepositoryUnavailableError from error

    async def set_stage(self, job_id: UUID, *, stage: str, progress: int) -> bool:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(IngestionJob).where(IngestionJob.id == job_id).with_for_update()
                )
                job = result.scalar_one_or_none()
                if (
                    job is None
                    or job.job_type != "document_processing"
                    or job.status != "processing"
                ):
                    return False
                job.stage = stage
                job.progress = progress
                await session.commit()
                return True
        except (SQLAlchemyError, OSError) as error:
            raise IngestionRepositoryUnavailableError from error

    async def complete_job(self, job_id: UUID, *, chunks: list[ChunkToSave]) -> bool:
        if not chunks:
            raise ValueError("A completed ingestion job requires at least one chunk.")
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
                if job.job_type != "document_processing" or job.status != "processing":
                    return False
                await session.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_version_id == version.id)
                )
                session.add_all(
                    [
                        DocumentChunk(
                            id=uuid4(),
                            document_version_id=version.id,
                            chunk_index=chunk.chunk_index,
                            heading_path=list(chunk.heading_path),
                            content=chunk.content,
                            content_hash=chunk.content_hash,
                            character_count=chunk.character_count,
                            enabled=chunk.enabled,
                        )
                        for chunk in chunks
                    ]
                )
                job.status = "completed"
                job.stage = "saving"
                job.progress = 100
                job.error_message = None
                job.finished_at = datetime.now(UTC)
                version.status = "ready_for_review"
                await session.commit()
                return True
        except (SQLAlchemyError, OSError) as error:
            raise IngestionRepositoryUnavailableError from error

    async def fail_job(self, job_id: UUID, *, error_message: str) -> None:
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
                if job.job_type != "document_processing" or job.status not in {
                    "pending",
                    "processing",
                }:
                    return
                job.status = "failed"
                job.error_message = error_message
                job.finished_at = datetime.now(UTC)
                version.status = "draft"
                await session.commit()
        except (SQLAlchemyError, OSError) as error:
            raise IngestionRepositoryUnavailableError from error
