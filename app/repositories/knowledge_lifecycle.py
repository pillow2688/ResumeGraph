from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentVersion, IngestionJob, KnowledgeDocument

DELETABLE_VERSION_STATUSES = {
    "draft",
    "indexing_failed",
    "ready_to_publish",
    "superseded",
}
ACTIVE_JOB_STATUSES = {"pending", "processing"}


class DatabaseSessionProvider(Protocol):
    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


@dataclass(frozen=True, slots=True)
class LifecycleScopeRecord:
    document_scope: Literal["profile", "project"]
    project_id: UUID | None


class ActiveDocumentJobRepositoryError(Exception):
    pass


class DocumentConfirmationRepositoryError(Exception):
    pass


class VersionNotDeletableRepositoryError(Exception):
    pass


class KnowledgeLifecycleRepositoryUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Knowledge lifecycle persistence is unavailable.")


def _scope(document: KnowledgeDocument) -> LifecycleScopeRecord:
    return LifecycleScopeRecord(
        document_scope=document.document_scope,
        project_id=document.project_id,
    )


class KnowledgeLifecycleRepository:
    def __init__(self, database: DatabaseSessionProvider) -> None:
        self._database = database

    async def delete_version(self, version_id: UUID) -> LifecycleScopeRecord | None:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(DocumentVersion, KnowledgeDocument)
                    .join(
                        KnowledgeDocument,
                        KnowledgeDocument.id == DocumentVersion.document_id,
                    )
                    .where(DocumentVersion.id == version_id)
                    .with_for_update()
                )
                row = result.one_or_none()
                if row is None:
                    return None
                version, document = row
                if (
                    document.current_published_version_id == version.id
                    or version.status not in DELETABLE_VERSION_STATUSES
                ):
                    raise VersionNotDeletableRepositoryError

                active_job_result = await session.execute(
                    select(IngestionJob.id).where(
                        IngestionJob.document_version_id == version.id,
                        IngestionJob.status.in_(ACTIVE_JOB_STATUSES),
                    )
                )
                if active_job_result.scalar_one_or_none() is not None:
                    raise ActiveDocumentJobRepositoryError

                scope = _scope(document)
                await session.delete(version)
                await session.commit()
                return scope
        except (
            ActiveDocumentJobRepositoryError,
            VersionNotDeletableRepositoryError,
        ):
            raise
        except (SQLAlchemyError, OSError) as error:
            raise KnowledgeLifecycleRepositoryUnavailableError from error

    async def delete_document(
        self,
        document_id: UUID,
        *,
        confirmation: str,
    ) -> LifecycleScopeRecord | None:
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
                if confirmation != document.title:
                    raise DocumentConfirmationRepositoryError

                active_job_result = await session.execute(
                    select(IngestionJob.id)
                    .join(
                        DocumentVersion,
                        DocumentVersion.id == IngestionJob.document_version_id,
                    )
                    .where(
                        DocumentVersion.document_id == document.id,
                        IngestionJob.status.in_(ACTIVE_JOB_STATUSES),
                    )
                    .limit(1)
                )
                if active_job_result.scalar_one_or_none() is not None:
                    raise ActiveDocumentJobRepositoryError

                scope = _scope(document)
                if document.current_published_version_id is not None:
                    document.current_published_version_id = None
                    await session.flush()
                await session.delete(document)
                await session.commit()
                return scope
        except (
            ActiveDocumentJobRepositoryError,
            DocumentConfirmationRepositoryError,
        ):
            raise
        except (SQLAlchemyError, OSError) as error:
            raise KnowledgeLifecycleRepositoryUnavailableError from error
