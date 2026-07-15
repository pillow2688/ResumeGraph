from contextlib import AbstractAsyncContextManager
from enum import StrEnum
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


class AdminDeleteOutcome(StrEnum):
    DELETED = "deleted"
    NOT_FOUND = "not_found"
    LAST_ADMIN = "last_admin"


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

    async def list_all(self) -> list[AdminUser]:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(AdminUser).order_by(AdminUser.username, AdminUser.id)
                )
                return list(result.scalars().all())
        except SQLAlchemyError as error:
            raise AdminRepositoryUnavailableError from error

    async def delete_if_not_last(self, admin_id: UUID) -> AdminDeleteOutcome:
        """Delete one administrator while serializing the last-admin invariant."""
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(AdminUser).order_by(AdminUser.id).with_for_update()
                )
                admins = list(result.scalars().all())
                target = next((admin for admin in admins if admin.id == admin_id), None)
                if target is None:
                    return AdminDeleteOutcome.NOT_FOUND
                if len(admins) == 1:
                    return AdminDeleteOutcome.LAST_ADMIN
                await session.delete(target)
                await session.commit()
        except SQLAlchemyError as error:
            raise AdminRepositoryUnavailableError from error
        return AdminDeleteOutcome.DELETED
