from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentVersion, KnowledgeDocument, Project

CONTENT_HASH_UNIQUE_CONSTRAINT = "uq_document_versions_document_content_hash"


class DatabaseSessionProvider(Protocol):
    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


@dataclass(frozen=True)
class DocumentVersionRecord:
    id: UUID
    document_id: UUID
    version_number: int
    source_type: str
    original_filename: str | None
    raw_content: str | None
    content_hash: str
    status: str
    created_at: datetime
    content_size_bytes: int


@dataclass(frozen=True)
class KnowledgeDocumentRecord:
    id: UUID
    project_id: UUID
    project_name: str
    title: str
    created_at: datetime
    updated_at: datetime
    version_count: int
    latest_version: DocumentVersionRecord | None


class DuplicateDocumentVersionRepositoryError(Exception):
    pass


class KnowledgeDocumentRepositoryUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Knowledge document persistence is unavailable.")


def _integrity_constraint_name(error: IntegrityError) -> str | None:
    original = error.orig
    candidates = (
        original,
        getattr(original, "__cause__", None),
        getattr(original, "__context__", None),
    )
    for candidate in candidates:
        if candidate is None:
            continue
        constraint_name = getattr(candidate, "constraint_name", None)
        if isinstance(constraint_name, str):
            return constraint_name
        diagnostics = getattr(candidate, "diag", None)
        constraint_name = getattr(diagnostics, "constraint_name", None)
        if isinstance(constraint_name, str):
            return constraint_name
    return None


def _to_version_record(version: DocumentVersion) -> DocumentVersionRecord:
    return DocumentVersionRecord(
        id=version.id,
        document_id=version.document_id,
        version_number=version.version_number,
        source_type=version.source_type,
        original_filename=version.original_filename,
        raw_content=version.raw_content,
        content_hash=version.content_hash,
        status=version.status,
        created_at=version.created_at,
        content_size_bytes=len(version.raw_content.encode("utf-8")),
    )


def _latest_version_subquery():
    return select(
        DocumentVersion.id.label("version_id"),
        DocumentVersion.document_id.label("document_id"),
        DocumentVersion.version_number.label("version_number"),
        DocumentVersion.source_type.label("source_type"),
        DocumentVersion.original_filename.label("original_filename"),
        DocumentVersion.content_hash.label("content_hash"),
        DocumentVersion.status.label("status"),
        DocumentVersion.created_at.label("version_created_at"),
        func.octet_length(DocumentVersion.raw_content).label("content_size_bytes"),
        func.count(DocumentVersion.id)
        .over(partition_by=DocumentVersion.document_id)
        .label("version_count"),
        func.row_number()
        .over(
            partition_by=DocumentVersion.document_id,
            order_by=DocumentVersion.version_number.desc(),
        )
        .label("row_number"),
    ).subquery()


def _record_from_row(row: object) -> KnowledgeDocumentRecord:
    values = tuple(row)
    document = values[0]
    project_name = values[1]
    (
        version_id,
        version_document_id,
        version_number,
        source_type,
        original_filename,
        content_hash,
        version_status,
        version_created_at,
        content_size_bytes,
        version_count,
    ) = values[2:]
    latest_version = None
    if version_id is not None:
        latest_version = DocumentVersionRecord(
            id=version_id,
            document_id=version_document_id,
            version_number=version_number,
            source_type=source_type,
            original_filename=original_filename,
            raw_content=None,
            content_hash=content_hash,
            status=version_status,
            created_at=version_created_at,
            content_size_bytes=content_size_bytes,
        )
    return KnowledgeDocumentRecord(
        id=document.id,
        project_id=document.project_id,
        project_name=project_name,
        title=document.title,
        created_at=document.created_at,
        updated_at=document.updated_at,
        version_count=int(version_count or 0),
        latest_version=latest_version,
    )


def _document_select():
    latest = _latest_version_subquery()
    return (
        select(
            KnowledgeDocument,
            Project.name,
            latest.c.version_id,
            latest.c.document_id,
            latest.c.version_number,
            latest.c.source_type,
            latest.c.original_filename,
            latest.c.content_hash,
            latest.c.status,
            latest.c.version_created_at,
            latest.c.content_size_bytes,
            latest.c.version_count,
        )
        .join(Project, Project.id == KnowledgeDocument.project_id)
        .outerjoin(
            latest,
            and_(
                latest.c.document_id == KnowledgeDocument.id,
                latest.c.row_number == 1,
            ),
        )
    )


class KnowledgeDocumentRepository:
    def __init__(self, database: DatabaseSessionProvider) -> None:
        self._database = database

    async def create_document(
        self,
        *,
        project_id: UUID,
        title: str,
        source_type: str,
        original_filename: str | None,
        raw_content: str,
        content_hash: str,
    ) -> KnowledgeDocumentRecord | None:
        try:
            async with self._database.session() as session:
                project_result = await session.execute(
                    select(Project).where(Project.id == project_id).with_for_update()
                )
                project = project_result.scalar_one_or_none()
                if project is None:
                    return None

                document = KnowledgeDocument(
                    id=uuid4(),
                    project_id=project_id,
                    title=title,
                )
                version = DocumentVersion(
                    id=uuid4(),
                    document_id=document.id,
                    version_number=1,
                    source_type=source_type,
                    original_filename=original_filename,
                    raw_content=raw_content,
                    content_hash=content_hash,
                    status="draft",
                )
                session.add(document)
                session.add(version)
                await session.flush()
                await session.refresh(document)
                await session.refresh(version)
                await session.commit()
                return KnowledgeDocumentRecord(
                    id=document.id,
                    project_id=document.project_id,
                    project_name=project.name,
                    title=document.title,
                    created_at=document.created_at,
                    updated_at=document.updated_at,
                    version_count=1,
                    latest_version=_to_version_record(version),
                )
        except (SQLAlchemyError, OSError) as error:
            raise KnowledgeDocumentRepositoryUnavailableError from error

    async def list_documents(
        self,
        project_id: UUID,
    ) -> list[KnowledgeDocumentRecord] | None:
        try:
            async with self._database.session() as session:
                project_result = await session.execute(
                    select(Project.id).where(Project.id == project_id)
                )
                if project_result.scalar_one_or_none() is None:
                    return None
                result = await session.execute(
                    _document_select()
                    .where(KnowledgeDocument.project_id == project_id)
                    .order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.id.desc())
                )
                return [_record_from_row(row) for row in result.all()]
        except (SQLAlchemyError, OSError) as error:
            raise KnowledgeDocumentRepositoryUnavailableError from error

    async def get_document(self, document_id: UUID) -> KnowledgeDocumentRecord | None:
        try:
            async with self._database.session() as session:
                return await self._get_document(session, document_id)
        except (SQLAlchemyError, OSError) as error:
            raise KnowledgeDocumentRepositoryUnavailableError from error

    async def update_document_title(
        self,
        document_id: UUID,
        *,
        title: str,
    ) -> KnowledgeDocumentRecord | None:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(KnowledgeDocument)
                    .where(KnowledgeDocument.id == document_id)
                    .with_for_update()
                )
                document = result.scalar_one_or_none()
                if document is None:
                    return None
                if document.title != title:
                    document.title = title
                    await session.flush()
                    await session.refresh(document)
                record = await self._get_document(session, document_id)
                await session.commit()
                return record
        except (SQLAlchemyError, OSError) as error:
            raise KnowledgeDocumentRepositoryUnavailableError from error

    async def create_version(
        self,
        document_id: UUID,
        *,
        source_type: str,
        original_filename: str | None,
        raw_content: str,
        content_hash: str,
    ) -> DocumentVersionRecord | None:
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

                duplicate_result = await session.execute(
                    select(DocumentVersion.id).where(
                        DocumentVersion.document_id == document_id,
                        DocumentVersion.content_hash == content_hash,
                    )
                )
                if duplicate_result.scalar_one_or_none() is not None:
                    raise DuplicateDocumentVersionRepositoryError

                number_result = await session.execute(
                    select(func.max(DocumentVersion.version_number)).where(
                        DocumentVersion.document_id == document_id
                    )
                )
                next_number = (number_result.scalar_one_or_none() or 0) + 1
                version = DocumentVersion(
                    id=uuid4(),
                    document_id=document_id,
                    version_number=next_number,
                    source_type=source_type,
                    original_filename=original_filename,
                    raw_content=raw_content,
                    content_hash=content_hash,
                    status="draft",
                )
                document.updated_at = datetime.now(UTC)
                session.add(version)
                try:
                    await session.flush()
                    await session.refresh(version)
                    await session.commit()
                except IntegrityError as error:
                    await session.rollback()
                    if _integrity_constraint_name(error) == CONTENT_HASH_UNIQUE_CONSTRAINT:
                        raise DuplicateDocumentVersionRepositoryError from error
                    raise
                return _to_version_record(version)
        except DuplicateDocumentVersionRepositoryError:
            raise
        except (SQLAlchemyError, OSError) as error:
            raise KnowledgeDocumentRepositoryUnavailableError from error

    async def list_versions(self, document_id: UUID) -> list[DocumentVersionRecord] | None:
        try:
            async with self._database.session() as session:
                document_result = await session.execute(
                    select(KnowledgeDocument.id).where(KnowledgeDocument.id == document_id)
                )
                if document_result.scalar_one_or_none() is None:
                    return None
                result = await session.execute(
                    select(
                        DocumentVersion.id,
                        DocumentVersion.document_id,
                        DocumentVersion.version_number,
                        DocumentVersion.source_type,
                        DocumentVersion.original_filename,
                        DocumentVersion.content_hash,
                        DocumentVersion.status,
                        DocumentVersion.created_at,
                        func.octet_length(DocumentVersion.raw_content).label("content_size_bytes"),
                    )
                    .where(DocumentVersion.document_id == document_id)
                    .order_by(DocumentVersion.version_number.desc())
                )
                return [
                    DocumentVersionRecord(
                        id=row[0],
                        document_id=row[1],
                        version_number=row[2],
                        source_type=row[3],
                        original_filename=row[4],
                        raw_content=None,
                        content_hash=row[5],
                        status=row[6],
                        created_at=row[7],
                        content_size_bytes=row[8],
                    )
                    for row in result.all()
                ]
        except (SQLAlchemyError, OSError) as error:
            raise KnowledgeDocumentRepositoryUnavailableError from error

    async def get_version(self, version_id: UUID) -> DocumentVersionRecord | None:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(DocumentVersion).where(DocumentVersion.id == version_id)
                )
                version = result.scalar_one_or_none()
                return _to_version_record(version) if version is not None else None
        except (SQLAlchemyError, OSError) as error:
            raise KnowledgeDocumentRepositoryUnavailableError from error

    async def _get_document(
        self,
        session: AsyncSession,
        document_id: UUID,
    ) -> KnowledgeDocumentRecord | None:
        result = await session.execute(
            _document_select().where(KnowledgeDocument.id == document_id)
        )
        row = result.one_or_none()
        return _record_from_row(row) if row is not None else None
