from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PublicDemoConfig

PUBLIC_DEMO_CONFIG_ID = 1


class DatabaseSessionProvider(Protocol):
    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


@dataclass(frozen=True)
class PublicDemoRecord:
    id: int
    candidate_name: str
    default_access_grant_id: UUID
    enabled: bool
    created_at: datetime
    updated_at: datetime


class PublicDemoRepositoryUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Public Demo persistence is unavailable.")


def _to_record(config: PublicDemoConfig) -> PublicDemoRecord:
    return PublicDemoRecord(
        id=config.id,
        candidate_name=config.candidate_name,
        default_access_grant_id=config.default_access_grant_id,
        enabled=config.enabled,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


class PublicDemoRepository:
    def __init__(self, database: DatabaseSessionProvider) -> None:
        self._database = database

    async def get(self) -> PublicDemoRecord | None:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(PublicDemoConfig).where(PublicDemoConfig.id == PUBLIC_DEMO_CONFIG_ID)
                )
                config = result.scalar_one_or_none()
                return _to_record(config) if config is not None else None
        except (SQLAlchemyError, OSError) as error:
            raise PublicDemoRepositoryUnavailableError from error

    async def upsert(
        self,
        *,
        candidate_name: str,
        default_access_grant_id: UUID,
        enabled: bool,
    ) -> PublicDemoRecord:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(PublicDemoConfig)
                    .where(PublicDemoConfig.id == PUBLIC_DEMO_CONFIG_ID)
                    .with_for_update()
                )
                config = result.scalar_one_or_none()
                if config is None:
                    config = PublicDemoConfig(
                        id=PUBLIC_DEMO_CONFIG_ID,
                        candidate_name=candidate_name,
                        default_access_grant_id=default_access_grant_id,
                        enabled=enabled,
                    )
                    session.add(config)
                else:
                    config.candidate_name = candidate_name
                    config.default_access_grant_id = default_access_grant_id
                    config.enabled = enabled
                    config.updated_at = datetime.now(UTC)
                await session.flush()
                record = _to_record(config)
                await session.commit()
                return record
        except (SQLAlchemyError, OSError) as error:
            raise PublicDemoRepositoryUnavailableError from error
