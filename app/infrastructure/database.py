from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.infrastructure.health import DependencyUnavailableError


class Database:
    """Own the reusable SQLAlchemy async engine and its connection pool."""

    def __init__(self, url: str, *, timeout_seconds: float = 3.0) -> None:
        self._engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_timeout=timeout_seconds,
            connect_args={
                "timeout": timeout_seconds,
                "command_timeout": timeout_seconds,
            },
        )
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session:
            yield session

    async def check_health(self) -> None:
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError) as error:
            raise DependencyUnavailableError("postgresql") from error

    async def close(self) -> None:
        await self._engine.dispose()
