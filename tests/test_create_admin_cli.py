import asyncio
import importlib
import importlib.util
from io import StringIO
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.models import AdminUser

TEST_PASSWORD = "fictional password for tests"


def load_cli_module():
    assert importlib.util.find_spec("app.cli") is not None, "CLI package must exist"
    name = "app.cli.create_admin"
    assert importlib.util.find_spec(name) is not None, f"{name} must exist"
    return importlib.import_module(name)


class FakeDatabase:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeRepository:
    def __init__(self, existing: AdminUser | None = None) -> None:
        self.user = existing
        self.created: AdminUser | None = None

    async def get_by_username(self, username: str) -> AdminUser | None:
        if self.user is not None and self.user.username == username:
            return self.user
        return None

    async def create(self, *, username: str, password_hash: str) -> AdminUser:
        self.created = AdminUser(id=uuid4(), username=username, password_hash=password_hash)
        self.user = self.created
        return self.created


def make_settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+asyncpg://resumegraph:local-only@postgres/resumegraph",
        redis_url="redis://redis:6379/0",
        dependency_timeout_seconds=7.0,
        _env_file=None,
    )


def test_cli_creates_normalized_admin_without_exposing_password_or_hash() -> None:
    cli = load_cli_module()
    database = FakeDatabase()
    repository = FakeRepository()
    output = StringIO()
    errors = StringIO()
    prompts: list[str] = []
    driver_timeouts: list[float] = []

    def read_password(prompt: str) -> str:
        prompts.append(prompt)
        return TEST_PASSWORD

    def build_database(_url: str, *, timeout_seconds: float) -> FakeDatabase:
        driver_timeouts.append(timeout_seconds)
        return database

    exit_code = asyncio.run(
        cli.run_create_admin(
            "  Admin  ",
            settings=make_settings(),
            password_reader=read_password,
            database_factory=build_database,
            repository_factory=lambda _database: repository,
            stdout=output,
            stderr=errors,
        )
    )

    assert exit_code == 0
    assert prompts == ["Password: ", "Confirm password: "]
    assert driver_timeouts == [7.0]
    assert repository.created is not None
    assert repository.created.username == "admin"
    assert repository.created.password_hash.startswith("$argon2")
    combined_output = output.getvalue() + errors.getvalue()
    assert TEST_PASSWORD not in combined_output
    assert repository.created.password_hash not in combined_output
    assert database.closed is True


def test_cli_duplicate_username_fails_safely_and_closes_database() -> None:
    cli = load_cli_module()
    database = FakeDatabase()
    existing = AdminUser(id=uuid4(), username="admin", password_hash="stored-hash")
    repository = FakeRepository(existing)
    output = StringIO()
    errors = StringIO()

    exit_code = asyncio.run(
        cli.run_create_admin(
            " ADMIN ",
            settings=make_settings(),
            password_reader=lambda _prompt: TEST_PASSWORD,
            database_factory=lambda _url, **_kwargs: database,
            repository_factory=lambda _database: repository,
            stdout=output,
            stderr=errors,
        )
    )

    assert exit_code != 0
    assert "already exists" in errors.getvalue().lower()
    assert TEST_PASSWORD not in errors.getvalue()
    assert "stored-hash" not in errors.getvalue()
    assert database.closed is True


def test_cli_rejects_password_mismatch_without_creating_admin() -> None:
    cli = load_cli_module()
    database = FakeDatabase()
    repository = FakeRepository()
    passwords = iter([TEST_PASSWORD, "different fictional password"])
    errors = StringIO()

    exit_code = asyncio.run(
        cli.run_create_admin(
            "admin",
            settings=make_settings(),
            password_reader=lambda _prompt: next(passwords),
            database_factory=lambda _url, **_kwargs: database,
            repository_factory=lambda _database: repository,
            stdout=StringIO(),
            stderr=errors,
        )
    )

    assert exit_code != 0
    assert repository.created is None
    assert TEST_PASSWORD not in errors.getvalue()
    assert database.closed is True


def test_cli_parser_has_no_plaintext_password_argument() -> None:
    cli = load_cli_module()

    with pytest.raises(SystemExit):
        cli.parse_args(["--username", "admin", "--password", TEST_PASSWORD])
