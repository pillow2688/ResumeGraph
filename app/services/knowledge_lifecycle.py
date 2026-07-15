import asyncio
from collections.abc import Awaitable
from typing import Protocol
from uuid import UUID

from app.repositories.knowledge_lifecycle import (
    ActiveDocumentJobRepositoryError,
    DocumentConfirmationRepositoryError,
    KnowledgeLifecycleRepositoryUnavailableError,
    LifecycleScopeRecord,
    VersionNotDeletableRepositoryError,
)
from app.services.deduplication import DeduplicationUnavailableError


class VersionNotFoundError(Exception):
    pass


class KnowledgeDocumentNotFoundError(Exception):
    pass


class VersionNotDeletableError(Exception):
    pass


class ActiveDocumentJobError(Exception):
    pass


class DocumentConfirmationError(Exception):
    pass


class KnowledgeLifecycleUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Knowledge lifecycle operation is temporarily unavailable.")


class KnowledgeLifecycleRepositoryBackend(Protocol):
    async def delete_version(self, version_id: UUID) -> LifecycleScopeRecord | None: ...

    async def delete_document(
        self,
        document_id: UUID,
        *,
        confirmation: str,
    ) -> LifecycleScopeRecord | None: ...


class DeduplicationServiceBackend(Protocol):
    async def rebuild_profile_scope(self) -> object: ...

    async def rebuild_project_scope(self, project_id: UUID) -> object: ...


async def _bounded[T](awaitable: Awaitable[T], timeout_seconds: float) -> T:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as error:
        raise KnowledgeLifecycleUnavailableError from error


class KnowledgeLifecycleService:
    def __init__(
        self,
        repository: KnowledgeLifecycleRepositoryBackend,
        deduplication_service: DeduplicationServiceBackend,
        *,
        dependency_timeout_seconds: float,
    ) -> None:
        self._repository = repository
        self._deduplication_service = deduplication_service
        self._dependency_timeout_seconds = dependency_timeout_seconds

    async def delete_version(self, version_id: UUID) -> None:
        try:
            scope = await _bounded(
                self._repository.delete_version(version_id),
                self._dependency_timeout_seconds,
            )
        except VersionNotDeletableRepositoryError as error:
            raise VersionNotDeletableError from error
        except ActiveDocumentJobRepositoryError as error:
            raise ActiveDocumentJobError from error
        except KnowledgeLifecycleRepositoryUnavailableError as error:
            raise KnowledgeLifecycleUnavailableError from error
        if scope is None:
            raise VersionNotFoundError
        await self._rebuild_scope(scope)

    async def delete_document(self, document_id: UUID, *, confirmation: str) -> None:
        try:
            scope = await _bounded(
                self._repository.delete_document(document_id, confirmation=confirmation),
                self._dependency_timeout_seconds,
            )
        except DocumentConfirmationRepositoryError as error:
            raise DocumentConfirmationError from error
        except ActiveDocumentJobRepositoryError as error:
            raise ActiveDocumentJobError from error
        except VersionNotDeletableRepositoryError as error:
            raise VersionNotDeletableError from error
        except KnowledgeLifecycleRepositoryUnavailableError as error:
            raise KnowledgeLifecycleUnavailableError from error
        if scope is None:
            raise KnowledgeDocumentNotFoundError
        await self._rebuild_scope(scope)

    async def _rebuild_scope(self, scope: LifecycleScopeRecord) -> None:
        try:
            if scope.document_scope == "profile":
                await _bounded(
                    self._deduplication_service.rebuild_profile_scope(),
                    self._dependency_timeout_seconds,
                )
            elif scope.project_id is not None:
                await _bounded(
                    self._deduplication_service.rebuild_project_scope(scope.project_id),
                    self._dependency_timeout_seconds,
                )
            else:
                raise KnowledgeLifecycleUnavailableError
        except DeduplicationUnavailableError as error:
            raise KnowledgeLifecycleUnavailableError from error
