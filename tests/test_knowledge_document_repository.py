import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models import DocumentVersion, KnowledgeDocument, Project
from app.repositories.knowledge_document import (
    DuplicateDocumentVersionRepositoryError,
    KnowledgeDocumentRepository,
    KnowledgeDocumentRepositoryUnavailableError,
)

NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)


class FakeScalars:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


class FakeResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def scalar_one_or_none(self):
        return self.values[0] if self.values else None

    def scalars(self) -> FakeScalars:
        return FakeScalars(self.values)

    def all(self) -> list[object]:
        return self.values


class FakeSession:
    def __init__(
        self,
        *,
        results: list[list[object]] | None = None,
        execute_error: Exception | None = None,
    ) -> None:
        self.results = list(results or [])
        self.execute_error = execute_error
        self.executed: list[object] = []
        self.added: list[object] = []
        self.commit_count = 0

    async def execute(self, statement) -> FakeResult:
        self.executed.append(statement)
        if self.execute_error is not None:
            raise self.execute_error
        return FakeResult(self.results.pop(0))

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        for item in self.added:
            if getattr(item, "created_at", None) is None:
                item.created_at = NOW
            if isinstance(item, KnowledgeDocument) and item.updated_at is None:
                item.updated_at = NOW

    async def refresh(self, _item: object) -> None:
        pass

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        pass


class ConstraintViolation(Exception):
    def __init__(self, constraint_name: str) -> None:
        super().__init__(constraint_name)
        self.constraint_name = constraint_name


class IntegrityFailingSession(FakeSession):
    def __init__(self, *, constraint_name: str, results: list[list[object]]) -> None:
        super().__init__(results=results)
        self.constraint_name = constraint_name

    async def flush(self) -> None:
        raise IntegrityError(
            "redacted statement",
            {},
            ConstraintViolation(self.constraint_name),
        )


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self.session_instance = session
        self.session_count = 0

    @asynccontextmanager
    async def session(self):
        self.session_count += 1
        yield self.session_instance


class ConcurrentVersionState:
    def __init__(self, document: KnowledgeDocument) -> None:
        self.document = document
        self.lock = asyncio.Lock()
        self.version_numbers = [1]
        self.content_hashes = {"a" * 64}
        self.active_lock_holders = 0
        self.max_active_lock_holders = 0


class ConcurrentVersionSession:
    def __init__(self, state: ConcurrentVersionState) -> None:
        self.state = state
        self.added: DocumentVersion | None = None
        self.holds_document_lock = False

    async def execute(self, statement) -> FakeResult:
        sql = str(statement).lower()
        if getattr(statement, "_for_update_arg", None) is not None:
            await self.state.lock.acquire()
            self.holds_document_lock = True
            self.state.active_lock_holders += 1
            self.state.max_active_lock_holders = max(
                self.state.max_active_lock_holders,
                self.state.active_lock_holders,
            )
            await asyncio.sleep(0)
            return FakeResult([self.state.document])
        if "content_hash" in sql:
            return FakeResult([])
        if "max(" in sql:
            return FakeResult([max(self.state.version_numbers)])
        raise AssertionError(f"Unexpected SQL in concurrency test: {sql}")

    def add(self, item: object) -> None:
        assert isinstance(item, DocumentVersion)
        self.added = item

    async def flush(self) -> None:
        assert self.added is not None
        assert self.added.version_number not in self.state.version_numbers
        assert self.added.content_hash not in self.state.content_hashes
        self.added.created_at = NOW
        self.state.version_numbers.append(self.added.version_number)
        self.state.content_hashes.add(self.added.content_hash)

    async def refresh(self, _item: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class ConcurrentVersionDatabase:
    def __init__(self, state: ConcurrentVersionState) -> None:
        self.state = state

    @asynccontextmanager
    async def session(self):
        session = ConcurrentVersionSession(self.state)
        try:
            yield session
        finally:
            if session.holds_document_lock:
                self.state.active_lock_holders -= 1
                self.state.lock.release()


def make_project() -> Project:
    return Project(
        id=uuid4(),
        name="ResumeGraph",
        description="Fictional",
        created_at=NOW,
        updated_at=NOW,
    )


def make_document(project: Project) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=uuid4(),
        project_id=project.id,
        title="Design",
        created_at=NOW,
        updated_at=NOW,
    )


def test_create_document_and_v1_lock_project_and_commit_atomically() -> None:
    project = make_project()
    session = FakeSession(results=[[project]])
    database = FakeDatabase(session)
    repository = KnowledgeDocumentRepository(database)

    record = asyncio.run(
        repository.create_document(
            project_id=project.id,
            title="Design",
            source_type="pasted_markdown",
            original_filename=None,
            raw_content="# v1",
            content_hash="a" * 64,
        )
    )

    assert record is not None
    assert database.session_count == 1
    assert session.executed[0]._for_update_arg is not None
    assert len(session.added) == 2
    assert session.commit_count == 1
    assert record.version_count == 1
    assert record.latest_version is not None
    assert record.latest_version.version_number == 1


def test_create_document_returns_none_for_missing_project_without_write() -> None:
    session = FakeSession(results=[[]])
    repository = KnowledgeDocumentRepository(FakeDatabase(session))

    record = asyncio.run(
        repository.create_document(
            project_id=uuid4(),
            title="Design",
            source_type="pasted_markdown",
            original_filename=None,
            raw_content="# v1",
            content_hash="a" * 64,
        )
    )

    assert record is None
    assert session.added == []
    assert session.commit_count == 0


def test_new_version_locks_document_and_computes_next_number_in_same_transaction() -> None:
    project = make_project()
    document = make_document(project)
    session = FakeSession(results=[[document], [], [1]])
    database = FakeDatabase(session)
    repository = KnowledgeDocumentRepository(database)

    record = asyncio.run(
        repository.create_version(
            document.id,
            source_type="markdown_file",
            original_filename="v2.md",
            raw_content="# v2",
            content_hash="b" * 64,
        )
    )

    assert record is not None
    assert database.session_count == 1
    assert session.executed[0]._for_update_arg is not None
    assert "content_hash" in str(session.executed[1])
    assert "max" in str(session.executed[2]).lower()
    assert record.version_number == 2
    assert session.commit_count == 1


def test_concurrent_version_creations_are_serialized_before_allocating_numbers() -> None:
    document = make_document(make_project())
    state = ConcurrentVersionState(document)
    repository = KnowledgeDocumentRepository(ConcurrentVersionDatabase(state))

    async def create_concurrently():
        return await asyncio.gather(
            repository.create_version(
                document.id,
                source_type="pasted_markdown",
                original_filename=None,
                raw_content="# v2-a",
                content_hash="b" * 64,
            ),
            repository.create_version(
                document.id,
                source_type="pasted_markdown",
                original_filename=None,
                raw_content="# v2-b",
                content_hash="c" * 64,
            ),
        )

    records = asyncio.run(create_concurrently())

    assert all(record is not None for record in records)
    assert sorted(record.version_number for record in records if record is not None) == [2, 3]
    assert sorted(state.version_numbers) == [1, 2, 3]
    assert state.max_active_lock_holders == 1


@pytest.mark.parametrize(
    ("constraint_name", "expected_error"),
    [
        (
            "uq_document_versions_document_content_hash",
            DuplicateDocumentVersionRepositoryError,
        ),
        (
            "uq_document_versions_document_version_number",
            KnowledgeDocumentRepositoryUnavailableError,
        ),
    ],
)
def test_version_integrity_errors_are_mapped_by_specific_constraint(
    constraint_name: str,
    expected_error: type[Exception],
) -> None:
    document = make_document(make_project())
    session = IntegrityFailingSession(
        constraint_name=constraint_name,
        results=[[document], [], [1]],
    )
    repository = KnowledgeDocumentRepository(FakeDatabase(session))

    with pytest.raises(expected_error):
        asyncio.run(
            repository.create_version(
                document.id,
                source_type="pasted_markdown",
                original_filename=None,
                raw_content="# v2",
                content_hash="b" * 64,
            )
        )


def test_document_list_is_stable_single_data_query_after_project_check() -> None:
    project = make_project()
    session = FakeSession(results=[[project], []])
    repository = KnowledgeDocumentRepository(FakeDatabase(session))

    records = asyncio.run(repository.list_documents(project.id))

    assert records == []
    assert len(session.executed) == 2
    sql = str(session.executed[1])
    assert "knowledge_documents.updated_at DESC" in sql
    assert "knowledge_documents.id DESC" in sql
    assert "row_number" in sql.lower()
    assert "octet_length(document_versions.raw_content)" in sql
    assert session.commit_count == 0


def test_version_list_orders_descending_and_does_not_commit() -> None:
    document = make_document(make_project())
    session = FakeSession(results=[[document], []])
    repository = KnowledgeDocumentRepository(FakeDatabase(session))

    records = asyncio.run(repository.list_versions(document.id))

    assert records == []
    assert "version_number DESC" in str(session.executed[1])
    assert session.commit_count == 0


@pytest.mark.parametrize(
    "database_error",
    [SQLAlchemyError("secret DSN"), OSError("driver raw error")],
)
def test_repository_sanitizes_database_failure(database_error: Exception) -> None:
    from app.repositories.knowledge_document import KnowledgeDocumentRepositoryUnavailableError

    session = FakeSession(execute_error=database_error)
    repository = KnowledgeDocumentRepository(FakeDatabase(session))

    with pytest.raises(KnowledgeDocumentRepositoryUnavailableError) as raised:
        asyncio.run(repository.list_documents(uuid4()))

    assert "secret" not in str(raised.value).lower()
    assert "driver" not in str(raised.value).lower()
