import asyncio
import importlib
import importlib.util
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError

from app.models import AccessGrant, GrantProject, Project


def load_repository_module():
    name = "app.repositories.access_grant"
    assert importlib.util.find_spec(name) is not None, f"{name} must exist"
    return importlib.import_module(name)


class FakeScalars:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class FakeResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._values)

    def scalar_one_or_none(self):
        return self._values[0] if self._values else None

    def one_or_none(self):
        return self._values[0] if self._values else None


class FakeSession:
    def __init__(
        self,
        *,
        results: list[list[object]] | None = None,
        execute_error: Exception | None = None,
    ) -> None:
        self.results = list(results or [])
        self.execute_error = execute_error
        self.executed_statements: list[object] = []
        self.added: AccessGrant | None = None
        self.commit_count = 0
        self.rollback_count = 0

    async def execute(self, statement) -> FakeResult:
        self.executed_statements.append(statement)
        if self.execute_error is not None:
            raise self.execute_error
        return FakeResult(self.results.pop(0))

    def add(self, value: AccessGrant) -> None:
        self.added = value

    async def flush(self) -> None:
        if self.added is not None:
            self.added.id = self.added.id or uuid4()
            self.added.created_at = datetime.now(UTC)

    async def refresh(self, _value: AccessGrant) -> None:
        pass

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    @asynccontextmanager
    async def session(self):
        yield self._session


def test_create_grant_writes_grant_and_links_in_one_commit() -> None:
    repository_module = load_repository_module()
    first = Project(id=uuid4(), name="Fictional ResumeGraph")
    second = Project(id=uuid4(), name="Fictional Search Service")
    session = FakeSession(results=[[first, second]])
    repository = repository_module.AccessGrantRepository(FakeDatabase(session))
    expires_at = datetime.now(UTC) + timedelta(days=7)

    created = asyncio.run(
        repository.create(
            name="Fictional recruiter grant",
            token_hash="digest-only",
            expires_at=expires_at,
            max_requests=100,
            project_ids=[first.id, second.id],
        )
    )

    assert session.commit_count == 1
    assert session.added is not None
    assert session.added.token_hash == "digest-only"
    assert not hasattr(session.added, "access_token")
    assert {link.project_id for link in session.added.project_links} == {first.id, second.id}
    assert created.token_hash == "digest-only"
    assert {project.id for project in created.projects} == {first.id, second.id}


def test_missing_project_aborts_before_any_grant_is_added_or_committed() -> None:
    repository_module = load_repository_module()
    existing = Project(id=uuid4(), name="Fictional Existing Project")
    missing_id = uuid4()
    session = FakeSession(results=[[existing]])
    repository = repository_module.AccessGrantRepository(FakeDatabase(session))

    with pytest.raises(repository_module.AccessGrantProjectNotFoundError):
        asyncio.run(
            repository.create(
                name="Fictional recruiter grant",
                token_hash="digest-only",
                expires_at=datetime.now(UTC) + timedelta(days=7),
                max_requests=100,
                project_ids=[existing.id, missing_id],
            )
        )

    assert session.added is None
    assert session.commit_count == 0


def test_repository_loads_safe_records_and_revokes_idempotently() -> None:
    repository_module = load_repository_module()
    project = Project(id=uuid4(), name="Fictional ResumeGraph")
    grant = AccessGrant(
        id=uuid4(),
        name="Fictional recruiter grant",
        token_hash="digest-only",
        expires_at=datetime.now(UTC) + timedelta(days=7),
        max_requests=100,
        request_count=0,
        created_at=datetime.now(UTC),
    )
    GrantProject(grant=grant, project=project)
    session = FakeSession(results=[[grant], [grant], [grant], [grant]])
    repository = repository_module.AccessGrantRepository(FakeDatabase(session))

    assert asyncio.run(repository.get_by_id(grant.id)).id == grant.id
    assert asyncio.run(repository.get_by_token_hash("digest-only")).id == grant.id
    revoked_at = datetime.now(UTC)
    first_revoke = asyncio.run(repository.revoke(grant.id, revoked_at=revoked_at))
    second_revoke = asyncio.run(
        repository.revoke(grant.id, revoked_at=revoked_at + timedelta(hours=1))
    )

    assert first_revoke.revoked_at == revoked_at
    assert second_revoke.revoked_at == revoked_at
    assert session.executed_statements[-2]._for_update_arg is not None
    assert session.executed_statements[-1]._for_update_arg is not None


def test_consume_request_uses_one_conditional_update_returning_statement() -> None:
    repository_module = load_repository_module()
    session = FakeSession(results=[[(4, 10)]])
    repository = repository_module.AccessGrantRepository(FakeDatabase(session))
    grant_id = uuid4()

    quota = asyncio.run(repository.consume_request(grant_id))

    assert quota.request_count == 4
    assert quota.max_requests == 10
    assert quota.remaining_requests == 6
    assert session.commit_count == 1
    assert len(session.executed_statements) == 1
    compiled = session.executed_statements[0].compile(dialect=postgresql.dialect())
    sql = " ".join(str(compiled).lower().split())
    assert sql.startswith("update access_grants set request_count=")
    assert "access_grants.request_count +" in sql
    assert "access_grants.request_count < access_grants.max_requests" in sql
    assert "access_grants.revoked_at is null" in sql
    assert "access_grants.expires_at > now()" in sql
    assert "returning access_grants.request_count, access_grants.max_requests" in sql
    assert compiled.params["id_1"] == grant_id


def test_consume_request_returns_none_when_the_atomic_guard_rejects_the_grant() -> None:
    repository_module = load_repository_module()
    session = FakeSession(results=[[]])
    repository = repository_module.AccessGrantRepository(FakeDatabase(session))

    assert asyncio.run(repository.consume_request(uuid4())) is None
    assert session.commit_count == 1


@pytest.mark.parametrize(
    "database_error",
    [SQLAlchemyError("driver failure"), ConnectionError("connection failure")],
)
def test_repository_translates_database_failure_without_driver_details(
    database_error: Exception,
) -> None:
    repository_module = load_repository_module()
    secret = "postgresql://admin:secret@database/resumegraph"
    database_error.args = (secret,)
    session = FakeSession(execute_error=database_error)
    repository = repository_module.AccessGrantRepository(FakeDatabase(session))

    with pytest.raises(repository_module.AccessGrantRepositoryUnavailableError) as raised:
        asyncio.run(repository.list())

    assert secret not in str(raised.value)
