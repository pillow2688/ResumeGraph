from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminUser


class DatabaseSessionProvider(Protocol):
    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


class DuplicateAdminUsernameError(Exception):
    def __init__(self) -> None:
        super().__init__("Administrator username already exists.")


class AdminRepositoryUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Administrator persistence is unavailable.")


class AdminUserRepository:
    def __init__(self, database: DatabaseSessionProvider) -> None:
        self._database = database

    async def get_by_username(self, username: str) -> AdminUser | None:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(AdminUser).where(AdminUser.username == username)
                )
        except SQLAlchemyError as error:
            raise AdminRepositoryUnavailableError from error
        return result.scalar_one_or_none()

    async def get_by_id(self, admin_id: UUID) -> AdminUser | None:
        try:
            async with self._database.session() as session:
                result = await session.execute(select(AdminUser).where(AdminUser.id == admin_id))
        except SQLAlchemyError as error:
            raise AdminRepositoryUnavailableError from error
        return result.scalar_one_or_none()

    async def create(self, *, username: str, password_hash: str) -> AdminUser:
        admin = AdminUser(username=username, password_hash=password_hash)
        try:
            async with self._database.session() as session:
                session.add(admin)
                try:
                    await session.commit()
                    await session.refresh(admin)
                except IntegrityError as error:
                    await session.rollback()
                    raise DuplicateAdminUsernameError from error
        except DuplicateAdminUsernameError:
            raise
        except SQLAlchemyError as error:
            raise AdminRepositoryUnavailableError from error
        return admin
