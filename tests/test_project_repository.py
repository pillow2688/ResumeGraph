import asyncio
import importlib
import importlib.util
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models import Project

NOW = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)


def load_repository_module():
    name = "app.repositories.project"
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


class FakeSession:
    def __init__(
        self,
        *,
        results: list[list[object]] | None = None,
        execute_error: Exception | None = None,
        commit_error: Exception | None = None,
    ) -> None:
        self.results = list(results or [])
        self.execute_error = execute_error
        self.commit_error = commit_error
        self.executed_statements: list[object] = []
        self.added: Project | None = None
        self.deleted: Project | None = None
        self.commit_count = 0
        self.rollback_count = 0

    async def execute(self, statement) -> FakeResult:
        self.executed_statements.append(statement)
        if self.execute_error is not None:
            raise self.execute_error
        return FakeResult(self.results.pop(0))

    def add(self, project: Project) -> None:
        self.added = project

    async def delete(self, project: Project) -> None:
        self.deleted = project

    async def flush(self) -> None:
        if self.added is not None:
            if getattr(self.added, "created_at", None) is None:
                self.added.created_at = NOW
            if getattr(self.added, "updated_at", None) is None:
                self.added.updated_at = NOW

    async def refresh(self, project: Project) -> None:
        if project.id is None:
            project.id = uuid4()

    async def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self.session_instance = session
        self.session_count = 0

    @asynccontextmanager
    async def session(self):
        self.session_count += 1
        yield self.session_instance


def make_project(*, name: str = "ResumeGraph", seconds: int = 0) -> Project:
    return Project(
        id=uuid4(),
        name=name,
        description="Fictional description",
        created_at=NOW + timedelta(seconds=seconds),
        updated_at=NOW + timedelta(seconds=seconds),
    )


def test_repository_creates_project_in_one_commit_and_returns_safe_record() -> None:
    repository_module = load_repository_module()
    session = FakeSession()
    repository = repository_module.ProjectRepository(FakeDatabase(session))

    record = asyncio.run(repository.create(name="ResumeGraph", description="Description"))

    assert session.added is not None
    assert session.added.name == "ResumeGraph"
    assert session.added.description == "Description"
    assert session.commit_count == 1
    assert record.id == session.added.id
    assert set(record.__dataclass_fields__) == {
        "id",
        "name",
        "description",
        "created_at",
        "updated_at",
    }


def test_repository_lists_in_stable_order_and_queries_do_not_commit() -> None:
    repository_module = load_repository_module()
    first = make_project(name="First", seconds=1)
    second = make_project(name="Second", seconds=2)
    session = FakeSession(results=[[second, first], [first]])
    repository = repository_module.ProjectRepository(FakeDatabase(session))

    listed = asyncio.run(repository.list())
    detail = asyncio.run(repository.get_by_id(first.id))

    assert [record.id for record in listed] == [second.id, first.id]
    assert detail is not None and detail.id == first.id
    assert session.commit_count == 0
    list_sql = str(session.executed_statements[0])
    assert "projects.created_at DESC" in list_sql
    assert "projects.id DESC" in list_sql


def test_repository_updates_under_row_lock_and_refreshes_record() -> None:
    repository_module = load_repository_module()
    project = make_project()
    session = FakeSession(results=[[project]])
    repository = repository_module.ProjectRepository(FakeDatabase(session))

    record = asyncio.run(
        repository.update(
            project.id,
            name="Renamed",
            description="Updated",
        )
    )

    assert record is not None
    assert record.name == "Renamed"
    assert record.description == "Updated"
    assert session.executed_statements[0]._for_update_arg is not None
    assert session.commit_count == 1


def test_repository_delete_locks_checks_and_deletes_in_one_session() -> None:
    repository_module = load_repository_module()
    project = make_project()
    session = FakeSession(results=[[project], [], []])
    database = FakeDatabase(session)
    repository = repository_module.ProjectRepository(database)

    outcome = asyncio.run(repository.delete(project.id))

    assert outcome is repository_module.ProjectDeleteOutcome.DELETED
    assert database.session_count == 1
    assert session.executed_statements[0]._for_update_arg is not None
    assert "grant_projects" in str(session.executed_statements[1])
    assert "knowledge_documents" in str(session.executed_statements[2])
    assert session.deleted is project
    assert session.commit_count == 1


def test_repository_delete_conflict_keeps_project_and_relationship_untouched() -> None:
    repository_module = load_repository_module()
    project = make_project()
    grant_id = uuid4()
    session = FakeSession(results=[[project], [grant_id]])
    repository = repository_module.ProjectRepository(FakeDatabase(session))

    outcome = asyncio.run(repository.delete(project.id))

    assert outcome is repository_module.ProjectDeleteOutcome.IN_USE
    assert session.deleted is None
    assert session.commit_count == 0
    assert session.rollback_count == 0


def test_repository_delete_document_conflict_keeps_project_and_document_untouched() -> None:
    repository_module = load_repository_module()
    project = make_project()
    document_id = uuid4()
    session = FakeSession(results=[[project], [], [document_id]])
    repository = repository_module.ProjectRepository(FakeDatabase(session))

    outcome = asyncio.run(repository.delete(project.id))

    assert outcome is repository_module.ProjectDeleteOutcome.IN_USE
    assert "knowledge_documents" in str(session.executed_statements[2])
    assert session.deleted is None
    assert session.commit_count == 0
    assert session.rollback_count == 0


def test_repository_delete_returns_not_found_without_writing() -> None:
    repository_module = load_repository_module()
    session = FakeSession(results=[[]])
    repository = repository_module.ProjectRepository(FakeDatabase(session))

    outcome = asyncio.run(repository.delete(uuid4()))

    assert outcome is repository_module.ProjectDeleteOutcome.NOT_FOUND
    assert session.deleted is None
    assert session.commit_count == 0


def test_delete_integrity_race_is_rolled_back_and_reported_as_in_use() -> None:
    repository_module = load_repository_module()
    project = make_project()
    error = IntegrityError("DELETE", {}, RuntimeError("foreign key conflict"))
    session = FakeSession(results=[[project], [], []], commit_error=error)
    repository = repository_module.ProjectRepository(FakeDatabase(session))

    outcome = asyncio.run(repository.delete(project.id))

    assert outcome is repository_module.ProjectDeleteOutcome.IN_USE
    assert session.rollback_count == 1


@pytest.mark.parametrize(
    "database_error",
    [SQLAlchemyError("driver failure"), OSError("connection failure")],
)
def test_repository_translates_database_failure_without_driver_details(
    database_error: Exception,
) -> None:
    repository_module = load_repository_module()
    secret = "postgresql://admin:secret@database/resumegraph"
    database_error.args = (secret,)
    session = FakeSession(execute_error=database_error)
    repository = repository_module.ProjectRepository(FakeDatabase(session))

    with pytest.raises(repository_module.ProjectRepositoryUnavailableError) as raised:
        asyncio.run(repository.list())

    assert secret not in str(raised.value)
