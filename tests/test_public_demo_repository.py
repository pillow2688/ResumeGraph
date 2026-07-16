import asyncio
import importlib
import importlib.util
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.models import PublicDemoConfig

NOW = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)


def load_repository_module():
    name = "app.repositories.public_demo"
    assert importlib.util.find_spec(name) is not None, f"{name} must exist"
    return importlib.import_module(name)


class FakeResult:
    def __init__(self, config: PublicDemoConfig | None) -> None:
        self._config = config

    def scalar_one_or_none(self) -> PublicDemoConfig | None:
        return self._config


class FakeSession:
    def __init__(
        self,
        *,
        result: PublicDemoConfig | None = None,
        execute_error: Exception | None = None,
    ) -> None:
        self.result = result
        self.execute_error = execute_error
        self.executed_statements: list[object] = []
        self.added: PublicDemoConfig | None = None
        self.commit_count = 0

    async def execute(self, statement: object) -> FakeResult:
        self.executed_statements.append(statement)
        if self.execute_error is not None:
            raise self.execute_error
        return FakeResult(self.result)

    def add(self, config: PublicDemoConfig) -> None:
        self.added = config

    async def flush(self) -> None:
        config = self.added or self.result
        if config is not None:
            config.created_at = getattr(config, "created_at", None) or NOW
            config.updated_at = NOW

    async def commit(self) -> None:
        self.commit_count += 1


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self.session_instance = session

    @asynccontextmanager
    async def session(self):
        yield self.session_instance


def make_config() -> PublicDemoConfig:
    return PublicDemoConfig(
        id=1,
        candidate_name="马腾飞",
        default_access_grant_id=uuid4(),
        enabled=True,
        created_at=NOW,
        updated_at=NOW,
    )


def test_repository_gets_the_singleton_without_writing() -> None:
    repository_module = load_repository_module()
    config = make_config()
    session = FakeSession(result=config)
    repository = repository_module.PublicDemoRepository(FakeDatabase(session))

    record = asyncio.run(repository.get())

    assert record is not None
    assert record.id == 1
    assert record.candidate_name == "马腾飞"
    assert record.default_access_grant_id == config.default_access_grant_id
    assert session.commit_count == 0
    assert "public_demo_config.id" in str(session.executed_statements[0])


def test_repository_upsert_creates_only_fixed_id_one() -> None:
    repository_module = load_repository_module()
    session = FakeSession()
    repository = repository_module.PublicDemoRepository(FakeDatabase(session))
    grant_id = uuid4()

    record = asyncio.run(
        repository.upsert(
            candidate_name="马腾飞",
            default_access_grant_id=grant_id,
            enabled=True,
        )
    )

    assert session.added is not None
    assert session.added.id == 1
    assert record.id == 1
    assert record.default_access_grant_id == grant_id
    assert session.commit_count == 1


def test_repository_upsert_updates_the_locked_singleton() -> None:
    repository_module = load_repository_module()
    config = make_config()
    session = FakeSession(result=config)
    repository = repository_module.PublicDemoRepository(FakeDatabase(session))
    replacement_grant_id = uuid4()

    record = asyncio.run(
        repository.upsert(
            candidate_name="马腾飞（更新）",
            default_access_grant_id=replacement_grant_id,
            enabled=False,
        )
    )

    assert session.added is None
    assert session.executed_statements[0]._for_update_arg is not None
    assert record.candidate_name == "马腾飞（更新）"
    assert record.default_access_grant_id == replacement_grant_id
    assert record.enabled is False
    assert session.commit_count == 1


def test_repository_translates_database_failure_without_driver_details() -> None:
    repository_module = load_repository_module()
    secret = "postgresql://admin:secret@database/resumegraph"
    session = FakeSession(execute_error=SQLAlchemyError(secret))
    repository = repository_module.PublicDemoRepository(FakeDatabase(session))

    with pytest.raises(repository_module.PublicDemoRepositoryUnavailableError) as raised:
        asyncio.run(repository.get())

    assert secret not in str(raised.value)
