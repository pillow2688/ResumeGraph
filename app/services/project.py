import asyncio
from collections.abc import Awaitable
from typing import Protocol
from uuid import UUID

from app.repositories.project import (
    ProjectDeleteOutcome,
    ProjectRecord,
    ProjectRepositoryUnavailableError,
)
from app.schemas.project import ProjectResponse


class ProjectRepositoryBackend(Protocol):
    async def create(self, *, name: str, description: str) -> ProjectRecord: ...

    async def list(self) -> list[ProjectRecord]: ...

    async def get_by_id(self, project_id: UUID) -> ProjectRecord | None: ...

    async def update(
        self,
        project_id: UUID,
        *,
        name: str | None,
        description: str | None,
    ) -> ProjectRecord | None: ...

    async def delete(self, project_id: UUID) -> ProjectDeleteOutcome: ...


class InvalidProjectRequestError(Exception):
    pass


class ProjectNotFoundError(Exception):
    pass


class ProjectInUseError(Exception):
    pass


class ProjectUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Project management is temporarily unavailable.")


async def _await_dependency[T](awaitable: Awaitable[T], timeout_seconds: float) -> T:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as error:
        raise ProjectUnavailableError from error


def _normalize_name(name: str) -> str:
    normalized = name.strip()
    if not normalized or len(normalized) > 200:
        raise InvalidProjectRequestError
    return normalized


def _normalize_description(description: str) -> str:
    normalized = description.strip()
    if len(normalized) > 5000:
        raise InvalidProjectRequestError
    return normalized


def _to_response(record: ProjectRecord) -> ProjectResponse:
    return ProjectResponse(
        id=record.id,
        name=record.name,
        description=record.description,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class ProjectService:
    def __init__(
        self,
        repository: ProjectRepositoryBackend,
        *,
        dependency_timeout_seconds: float = 3.0,
    ) -> None:
        self._repository = repository
        self._dependency_timeout_seconds = dependency_timeout_seconds

    async def create_project(self, *, name: str, description: str) -> ProjectResponse:
        normalized_name = _normalize_name(name)
        normalized_description = _normalize_description(description)
        try:
            record = await _await_dependency(
                self._repository.create(
                    name=normalized_name,
                    description=normalized_description,
                ),
                self._dependency_timeout_seconds,
            )
        except ProjectRepositoryUnavailableError as error:
            raise ProjectUnavailableError from error
        return _to_response(record)

    async def list_projects(self) -> list[ProjectResponse]:
        try:
            records = await _await_dependency(
                self._repository.list(),
                self._dependency_timeout_seconds,
            )
        except ProjectRepositoryUnavailableError as error:
            raise ProjectUnavailableError from error
        return [_to_response(record) for record in records]

    async def get_project(self, project_id: UUID) -> ProjectResponse:
        record = await self._get_record(project_id)
        if record is None:
            raise ProjectNotFoundError
        return _to_response(record)

    async def update_project(
        self,
        project_id: UUID,
        *,
        name: str | None,
        description: str | None,
    ) -> ProjectResponse:
        if name is None and description is None:
            raise InvalidProjectRequestError
        normalized_name = _normalize_name(name) if name is not None else None
        normalized_description = (
            _normalize_description(description) if description is not None else None
        )
        try:
            record = await _await_dependency(
                self._repository.update(
                    project_id,
                    name=normalized_name,
                    description=normalized_description,
                ),
                self._dependency_timeout_seconds,
            )
        except ProjectRepositoryUnavailableError as error:
            raise ProjectUnavailableError from error
        if record is None:
            raise ProjectNotFoundError
        return _to_response(record)

    async def delete_project(self, project_id: UUID) -> None:
        try:
            outcome = await _await_dependency(
                self._repository.delete(project_id),
                self._dependency_timeout_seconds,
            )
        except ProjectRepositoryUnavailableError as error:
            raise ProjectUnavailableError from error
        if outcome is ProjectDeleteOutcome.NOT_FOUND:
            raise ProjectNotFoundError
        if outcome is ProjectDeleteOutcome.IN_USE:
            raise ProjectInUseError

    async def _get_record(self, project_id: UUID) -> ProjectRecord | None:
        try:
            return await _await_dependency(
                self._repository.get_by_id(project_id),
                self._dependency_timeout_seconds,
            )
        except ProjectRepositoryUnavailableError as error:
            raise ProjectUnavailableError from error
