from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AccessGrant, GrantProject, Project


class DatabaseSessionProvider(Protocol):
    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


@dataclass(frozen=True)
class ProjectRecord:
    id: UUID
    name: str


@dataclass(frozen=True)
class AccessGrantRecord:
    id: UUID
    name: str
    token_hash: str
    expires_at: datetime
    max_requests: int
    request_count: int
    revoked_at: datetime | None
    created_at: datetime
    projects: tuple[ProjectRecord, ...]


@dataclass(frozen=True, slots=True)
class RequestQuotaRecord:
    request_count: int
    max_requests: int

    @property
    def remaining_requests(self) -> int:
        return self.max_requests - self.request_count


class AccessGrantProjectNotFoundError(Exception):
    pass


class AccessGrantRepositoryUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Access grant persistence is unavailable.")


def _grant_select() -> Select[tuple[AccessGrant]]:
    return select(AccessGrant).options(
        selectinload(AccessGrant.project_links).selectinload(GrantProject.project)
    )


def _to_record(grant: AccessGrant) -> AccessGrantRecord:
    projects = tuple(
        sorted(
            (
                ProjectRecord(id=link.project.id, name=link.project.name)
                for link in grant.project_links
            ),
            key=lambda project: (project.name, str(project.id)),
        )
    )
    return AccessGrantRecord(
        id=grant.id,
        name=grant.name,
        token_hash=grant.token_hash,
        expires_at=grant.expires_at,
        max_requests=grant.max_requests,
        request_count=grant.request_count,
        revoked_at=grant.revoked_at,
        created_at=grant.created_at,
        projects=projects,
    )


class AccessGrantRepository:
    def __init__(self, database: DatabaseSessionProvider) -> None:
        self._database = database

    async def create(
        self,
        *,
        name: str,
        token_hash: str,
        expires_at: datetime,
        max_requests: int,
        project_ids: list[UUID],
    ) -> AccessGrantRecord:
        unique_project_ids = list(dict.fromkeys(project_ids))
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(Project).where(Project.id.in_(unique_project_ids))
                )
                projects = list(result.scalars().all())
                if {project.id for project in projects} != set(unique_project_ids):
                    raise AccessGrantProjectNotFoundError

                grant = AccessGrant(
                    id=uuid4(),
                    name=name,
                    token_hash=token_hash,
                    expires_at=expires_at,
                    max_requests=max_requests,
                )
                grant.project_links = [
                    GrantProject(
                        grant_id=grant.id,
                        project_id=project.id,
                        project=project,
                    )
                    for project in projects
                ]
                session.add(grant)
                await session.flush()
                await session.commit()
                return _to_record(grant)
        except AccessGrantProjectNotFoundError:
            raise
        except (SQLAlchemyError, OSError) as error:
            raise AccessGrantRepositoryUnavailableError from error

    async def list(self) -> list[AccessGrantRecord]:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    _grant_select().order_by(AccessGrant.created_at.desc(), AccessGrant.id.desc())
                )
                return [_to_record(grant) for grant in result.scalars().all()]
        except (SQLAlchemyError, OSError) as error:
            raise AccessGrantRepositoryUnavailableError from error

    async def get_by_id(self, grant_id: UUID) -> AccessGrantRecord | None:
        return await self._get_one(_grant_select().where(AccessGrant.id == grant_id))

    async def get_by_token_hash(self, token_hash: str) -> AccessGrantRecord | None:
        return await self._get_one(_grant_select().where(AccessGrant.token_hash == token_hash))

    async def revoke(
        self,
        grant_id: UUID,
        *,
        revoked_at: datetime,
    ) -> AccessGrantRecord | None:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    _grant_select().where(AccessGrant.id == grant_id).with_for_update()
                )
                grant = result.scalar_one_or_none()
                if grant is None:
                    return None
                if grant.revoked_at is None:
                    grant.revoked_at = revoked_at
                await session.commit()
                return _to_record(grant)
        except (SQLAlchemyError, OSError) as error:
            raise AccessGrantRepositoryUnavailableError from error

    async def consume_request(self, grant_id: UUID) -> RequestQuotaRecord | None:
        """Atomically reserve one request without a SELECT/increment race."""
        statement = (
            update(AccessGrant)
            .where(
                AccessGrant.id == grant_id,
                AccessGrant.request_count < AccessGrant.max_requests,
                AccessGrant.revoked_at.is_(None),
                AccessGrant.expires_at > func.now(),
            )
            .values(request_count=AccessGrant.request_count + 1)
            .returning(AccessGrant.request_count, AccessGrant.max_requests)
        )
        try:
            async with self._database.session() as session:
                result = await session.execute(statement)
                row = result.one_or_none()
                await session.commit()
                if row is None:
                    return None
                return RequestQuotaRecord(
                    request_count=row[0],
                    max_requests=row[1],
                )
        except (SQLAlchemyError, OSError) as error:
            raise AccessGrantRepositoryUnavailableError from error

    async def _get_one(
        self,
        statement: Select[tuple[AccessGrant]],
    ) -> AccessGrantRecord | None:
        try:
            async with self._database.session() as session:
                result = await session.execute(statement)
                grant = result.scalar_one_or_none()
                return _to_record(grant) if grant is not None else None
        except (SQLAlchemyError, OSError) as error:
            raise AccessGrantRepositoryUnavailableError from error
