import asyncio
from uuid import UUID, uuid4

import pytest

from app.models import AdminUser
from app.repositories.admin_user import (
    AdminDeleteOutcome,
    AdminRepositoryUnavailableError,
)
from app.services.admin_auth import AdminUsernameExistsError
from app.services.admin_user_management import (
    AdminUserManagementService,
    AdminUserManagementUnavailableError,
    CannotDeleteCurrentAdminError,
    LastAdminDeletionError,
    ManagedAdminNotFoundError,
)


class FakeAdminRepository:
    def __init__(self, users: list[AdminUser]) -> None:
        self.users = users
        self.unavailable = False

    async def get_by_username(self, username: str) -> AdminUser | None:
        return next((user for user in self.users if user.username == username), None)

    async def get_by_id(self, admin_id: UUID) -> AdminUser | None:
        return next((user for user in self.users if user.id == admin_id), None)

    async def create(self, *, username: str, password_hash: str) -> AdminUser:
        user = AdminUser(id=uuid4(), username=username, password_hash=password_hash)
        self.users.append(user)
        return user

    async def list_all(self) -> list[AdminUser]:
        if self.unavailable:
            raise AdminRepositoryUnavailableError
        return sorted(self.users, key=lambda user: (user.username, str(user.id)))

    async def delete_if_not_last(self, admin_id: UUID) -> AdminDeleteOutcome:
        if self.unavailable:
            raise AdminRepositoryUnavailableError
        target = next((user for user in self.users if user.id == admin_id), None)
        if target is None:
            return AdminDeleteOutcome.NOT_FOUND
        if len(self.users) == 1:
            return AdminDeleteOutcome.LAST_ADMIN
        self.users.remove(target)
        return AdminDeleteOutcome.DELETED


def make_admin(username: str) -> AdminUser:
    return AdminUser(id=uuid4(), username=username, password_hash="not-returned")


def test_lists_safe_admin_summaries_in_stable_order() -> None:
    repository = FakeAdminRepository([make_admin("zoe"), make_admin("admin")])
    service = AdminUserManagementService(repository)

    result = asyncio.run(service.list_admins())

    assert [admin.username for admin in result] == ["admin", "zoe"]
    assert all(not hasattr(admin, "password_hash") for admin in result)


def test_creates_admin_through_existing_password_hashing_boundary() -> None:
    repository = FakeAdminRepository([make_admin("admin")])
    service = AdminUserManagementService(repository)

    created = asyncio.run(service.create_admin("  Reviewer  ", "correct horse battery staple"))

    assert created.username == "reviewer"
    stored = next(user for user in repository.users if user.id == created.id)
    assert stored.password_hash.startswith("$argon2")


def test_duplicate_admin_username_is_rejected() -> None:
    repository = FakeAdminRepository([make_admin("admin")])
    service = AdminUserManagementService(repository)

    with pytest.raises(AdminUsernameExistsError):
        asyncio.run(service.create_admin(" ADMIN ", "correct horse battery staple"))


def test_current_admin_cannot_delete_self() -> None:
    current = make_admin("admin")
    service = AdminUserManagementService(FakeAdminRepository([current, make_admin("reviewer")]))

    with pytest.raises(CannotDeleteCurrentAdminError):
        asyncio.run(service.delete_admin(target_admin_id=current.id, current_admin_id=current.id))


def test_last_admin_cannot_be_deleted() -> None:
    current = make_admin("admin")
    service = AdminUserManagementService(FakeAdminRepository([current]))

    with pytest.raises(LastAdminDeletionError):
        asyncio.run(service.delete_admin(target_admin_id=current.id, current_admin_id=uuid4()))


def test_missing_admin_returns_not_found() -> None:
    current = make_admin("admin")
    service = AdminUserManagementService(FakeAdminRepository([current, make_admin("reviewer")]))

    with pytest.raises(ManagedAdminNotFoundError):
        asyncio.run(service.delete_admin(target_admin_id=uuid4(), current_admin_id=current.id))


def test_repository_failure_is_sanitized() -> None:
    repository = FakeAdminRepository([make_admin("admin")])
    repository.unavailable = True
    service = AdminUserManagementService(repository)

    with pytest.raises(AdminUserManagementUnavailableError) as raised:
        asyncio.run(service.list_admins())

    assert "database" not in str(raised.value).lower()
    assert "postgresql" not in str(raised.value).lower()
