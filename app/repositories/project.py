from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GrantProject, KnowledgeDocument, Project


class DatabaseSessionProvider(Protocol):
    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


@dataclass(frozen=True)
class ProjectRecord:
    id: UUID
    name: str
    description: str
    created_at: datetime
    updated_at: datetime


class ProjectDeleteOutcome(Enum):
    DELETED = "deleted"
    IN_USE = "in_use"
    NOT_FOUND = "not_found"


class ProjectRepositoryUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Project persistence is unavailable.")


def _to_record(project: Project) -> ProjectRecord:
    return ProjectRecord(
        id=project.id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


class ProjectRepository:
    def __init__(self, database: DatabaseSessionProvider) -> None:
        self._database = database

    async def create(self, *, name: str, description: str) -> ProjectRecord:
        project = Project(name=name, description=description)
        try:
            async with self._database.session() as session:
                session.add(project)
                await session.flush()
                await session.refresh(project)
                await session.commit()
                return _to_record(project)
        except (SQLAlchemyError, OSError) as error:
            raise ProjectRepositoryUnavailableError from error

    async def list(self) -> list[ProjectRecord]:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(Project).order_by(Project.created_at.desc(), Project.id.desc())
                )
                return [_to_record(project) for project in result.scalars().all()]
        except (SQLAlchemyError, OSError) as error:
            raise ProjectRepositoryUnavailableError from error

    async def get_by_id(self, project_id: UUID) -> ProjectRecord | None:
        try:
            async with self._database.session() as session:
                result = await session.execute(select(Project).where(Project.id == project_id))
                project = result.scalar_one_or_none()
                return _to_record(project) if project is not None else None
        except (SQLAlchemyError, OSError) as error:
            raise ProjectRepositoryUnavailableError from error

    async def update(
        self,
        project_id: UUID,
        *,
        name: str | None,
        description: str | None,
    ) -> ProjectRecord | None:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(Project).where(Project.id == project_id).with_for_update()
                )
                project = result.scalar_one_or_none()
                if project is None:
                    return None
                if name is not None:
                    project.name = name
                if description is not None:
                    project.description = description
                await session.flush()
                await session.refresh(project)
                await session.commit()
                return _to_record(project)
        except (SQLAlchemyError, OSError) as error:
            raise ProjectRepositoryUnavailableError from error

    async def delete(self, project_id: UUID) -> ProjectDeleteOutcome:
        try:
            async with self._database.session() as session:
                project_result = await session.execute(
                    select(Project).where(Project.id == project_id).with_for_update()
                )
                project = project_result.scalar_one_or_none()
                if project is None:
                    return ProjectDeleteOutcome.NOT_FOUND

                reference_result = await session.execute(
                    select(GrantProject.grant_id)
                    .where(GrantProject.project_id == project_id)
                    .limit(1)
                )
                if reference_result.scalar_one_or_none() is not None:
                    return ProjectDeleteOutcome.IN_USE

                document_reference_result = await session.execute(
                    select(KnowledgeDocument.id)
                    .where(KnowledgeDocument.project_id == project_id)
                    .limit(1)
                )
                if document_reference_result.scalar_one_or_none() is not None:
                    return ProjectDeleteOutcome.IN_USE

                await session.delete(project)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    return ProjectDeleteOutcome.IN_USE
                return ProjectDeleteOutcome.DELETED
        except (SQLAlchemyError, OSError) as error:
            raise ProjectRepositoryUnavailableError from error
