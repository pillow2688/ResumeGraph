import asyncio
from collections.abc import Awaitable
from typing import Protocol
from uuid import UUID

from app.models import AdminUser
from app.repositories.admin_user import (
    AdminDeleteOutcome,
    AdminRepositoryUnavailableError,
)
from app.schemas.admin_auth import AdminPrincipal
from app.services.admin_auth import AdminAccountService, AdminAuthUnavailableError


class AdminManagementRepository(Protocol):
    async def get_by_username(self, username: str) -> AdminUser | None: ...

    async def get_by_id(self, admin_id: UUID) -> AdminUser | None: ...

    async def create(self, *, username: str, password_hash: str) -> AdminUser: ...

    async def list_all(self) -> list[AdminUser]: ...

    async def delete_if_not_last(self, admin_id: UUID) -> AdminDeleteOutcome: ...


class ManagedAdminNotFoundError(Exception):
    pass


class CannotDeleteCurrentAdminError(Exception):
    pass


class LastAdminDeletionError(Exception):
    pass


class AdminUserManagementUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Administrator management is temporarily unavailable.")


async def _await_dependency[T](awaitable: Awaitable[T], timeout_seconds: float) -> T:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as error:
        raise AdminUserManagementUnavailableError from error


class AdminUserManagementService:
    def __init__(
        self,
        repository: AdminManagementRepository,
        *,
        dependency_timeout_seconds: float = 3.0,
    ) -> None:
        self._repository = repository
        self._dependency_timeout_seconds = dependency_timeout_seconds

    async def list_admins(self) -> list[AdminPrincipal]:
        try:
            admins = await _await_dependency(
                self._repository.list_all(), self._dependency_timeout_seconds
            )
        except AdminRepositoryUnavailableError as error:
            raise AdminUserManagementUnavailableError from error
        return [AdminPrincipal(id=admin.id, username=admin.username) for admin in admins]

    async def create_admin(self, username: str, password: str) -> AdminPrincipal:
        try:
            return await AdminAccountService(
                self._repository,
                dependency_timeout_seconds=self._dependency_timeout_seconds,
            ).create_admin(username, password)
        except AdminAuthUnavailableError as error:
            raise AdminUserManagementUnavailableError from error

    async def delete_admin(self, *, target_admin_id: UUID, current_admin_id: UUID) -> None:
        if target_admin_id == current_admin_id:
            raise CannotDeleteCurrentAdminError
        try:
            outcome = await _await_dependency(
                self._repository.delete_if_not_last(target_admin_id),
                self._dependency_timeout_seconds,
            )
        except AdminRepositoryUnavailableError as error:
            raise AdminUserManagementUnavailableError from error
        if outcome == AdminDeleteOutcome.NOT_FOUND:
            raise ManagedAdminNotFoundError
        if outcome == AdminDeleteOutcome.LAST_ADMIN:
            raise LastAdminDeletionError
