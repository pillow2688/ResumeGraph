import asyncio
import importlib
import importlib.util
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models import AdminUser


def load_repository_module():
    assert importlib.util.find_spec("app.repositories") is not None, "repository package must exist"
    name = "app.repositories.admin_user"
    assert importlib.util.find_spec(name) is not None, f"{name} must exist"
    return importlib.import_module(name)


class FakeResult:
    def __init__(self, user: AdminUser | None) -> None:
        self._user = user

    def scalar_one_or_none(self) -> AdminUser | None:
        return self._user


class FakeSession:
    def __init__(
        self,
        *,
        result: AdminUser | None = None,
        execute_error: SQLAlchemyError | None = None,
        commit_error: SQLAlchemyError | None = None,
    ) -> None:
        self.result = result
        self.execute_error = execute_error
        self.commit_error = commit_error
        self.added: AdminUser | None = None
        self.committed = False
        self.rolled_back = False

    async def execute(self, _statement):
        if self.execute_error is not None:
            raise self.execute_error
        return FakeResult(self.result)

    def add(self, user: AdminUser) -> None:
        self.added = user

    async def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def refresh(self, user: AdminUser) -> None:
        if user.id is None:
            user.id = uuid4()


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    @asynccontextmanager
    async def session(self):
        yield self._session


def test_repository_finds_admin_by_username_and_id() -> None:
    repository_module = load_repository_module()
    user = AdminUser(id=uuid4(), username="admin", password_hash="argon2-hash")
    session = FakeSession(result=user)
    repository = repository_module.AdminUserRepository(FakeDatabase(session))

    assert asyncio.run(repository.get_by_username("admin")) is user
    assert asyncio.run(repository.get_by_id(user.id)) is user


def test_repository_creates_only_normalized_username_and_password_hash() -> None:
    repository_module = load_repository_module()
    session = FakeSession()
    repository = repository_module.AdminUserRepository(FakeDatabase(session))

    created = asyncio.run(repository.create(username="admin", password_hash="argon2-hash"))

    assert isinstance(created.id, UUID)
    assert created.username == "admin"
    assert created.password_hash == "argon2-hash"
    assert not hasattr(created, "password")
    assert session.added is created
    assert session.committed is True


def test_repository_translates_duplicate_username_without_leaking_driver_error() -> None:
    repository_module = load_repository_module()
    secret = "postgresql://admin:secret@database/resumegraph"
    error = IntegrityError("INSERT", {}, RuntimeError(secret))
    session = FakeSession(commit_error=error)
    repository = repository_module.AdminUserRepository(FakeDatabase(session))

    with pytest.raises(repository_module.DuplicateAdminUsernameError) as raised:
        asyncio.run(repository.create(username="admin", password_hash="argon2-hash"))

    assert session.rolled_back is True
    assert secret not in str(raised.value)


def test_repository_translates_database_failure_without_leaking_driver_error() -> None:
    repository_module = load_repository_module()
    secret = "postgresql://admin:secret@database/resumegraph"
    session = FakeSession(execute_error=SQLAlchemyError(secret))
    repository = repository_module.AdminUserRepository(FakeDatabase(session))

    with pytest.raises(repository_module.AdminRepositoryUnavailableError) as raised:
        asyncio.run(repository.get_by_username("admin"))

    assert secret not in str(raised.value)
