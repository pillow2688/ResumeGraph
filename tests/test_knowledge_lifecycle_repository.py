import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.models import DocumentVersion, IngestionJob, KnowledgeDocument
from app.repositories.knowledge_lifecycle import (
    ActiveDocumentJobRepositoryError,
    DocumentConfirmationRepositoryError,
    KnowledgeLifecycleRepository,
    VersionNotDeletableRepositoryError,
)

NOW = datetime(2026, 7, 15, 17, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, values: object) -> None:
        self.values = values if isinstance(values, list) else [values]

    def one_or_none(self):
        if not self.values or self.values[0] is None:
            return None
        value = self.values[0]
        return value if isinstance(value, tuple) else value

    def scalar_one_or_none(self):
        return self.values[0] if self.values and self.values[0] is not None else None


class FakeSession:
    def __init__(self, results: list[object]) -> None:
        self.results = list(results)
        self.executed: list[object] = []
        self.deleted: list[object] = []
        self.commit_count = 0
        self.flush_count = 0

    async def execute(self, statement: object) -> FakeResult:
        self.executed.append(statement)
        return FakeResult(self.results.pop(0))

    async def delete(self, item: object) -> None:
        self.deleted.append(item)

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self.session_instance = session

    @asynccontextmanager
    async def session(self):
        yield self.session_instance


def document(*, scope: str = "profile") -> KnowledgeDocument:
    return KnowledgeDocument(
        id=uuid4(),
        project_id=None if scope == "profile" else uuid4(),
        document_scope=scope,
        title="Fictional resume",
        created_at=NOW,
        updated_at=NOW,
    )


def version(item: KnowledgeDocument, *, status: str = "superseded") -> DocumentVersion:
    return DocumentVersion(
        id=uuid4(),
        document_id=item.id,
        version_number=1,
        source_type="pasted_markdown",
        original_filename=None,
        raw_content="# Fictional resume",
        content_hash="a" * 64,
        status=status,
        created_at=NOW,
    )


@pytest.mark.parametrize("status", ["draft", "indexing_failed", "ready_to_publish", "superseded"])
def test_delete_noncurrent_version_allows_only_safe_terminal_states(status: str) -> None:
    item = document()
    item_version = version(item, status=status)
    session = FakeSession([[(item_version, item)], []])
    repository = KnowledgeLifecycleRepository(FakeDatabase(session))

    scope = asyncio.run(repository.delete_version(item_version.id))

    assert scope is not None and scope.document_scope == "profile"
    assert session.deleted == [item_version]
    assert session.commit_count == 1


def test_delete_version_rejects_current_published_invalid_state_and_active_job() -> None:
    item = document()
    current = version(item, status="published")
    item.current_published_version_id = current.id
    current_session = FakeSession([[(current, item)]])
    with pytest.raises(VersionNotDeletableRepositoryError):
        asyncio.run(
            KnowledgeLifecycleRepository(FakeDatabase(current_session)).delete_version(current.id)
        )

    invalid = version(item, status="ready_for_review")
    invalid_session = FakeSession([[(invalid, item)]])
    with pytest.raises(VersionNotDeletableRepositoryError):
        asyncio.run(
            KnowledgeLifecycleRepository(FakeDatabase(invalid_session)).delete_version(invalid.id)
        )

    deletable = version(item, status="draft")
    active_job = IngestionJob(id=uuid4(), document_version_id=deletable.id, status="processing")
    active_session = FakeSession([[(deletable, item)], [active_job.id]])
    with pytest.raises(ActiveDocumentJobRepositoryError):
        asyncio.run(
            KnowledgeLifecycleRepository(FakeDatabase(active_session)).delete_version(deletable.id)
        )
    assert active_session.deleted == []
    assert active_session.commit_count == 0


def test_permanent_delete_requires_exact_title_and_no_active_job_then_cascades() -> None:
    item = document(scope="project")
    mismatch_session = FakeSession([[item]])
    with pytest.raises(DocumentConfirmationRepositoryError):
        asyncio.run(
            KnowledgeLifecycleRepository(FakeDatabase(mismatch_session)).delete_document(
                item.id,
                confirmation="wrong title",
            )
        )

    active_session = FakeSession([[item], [uuid4()]])
    with pytest.raises(ActiveDocumentJobRepositoryError):
        asyncio.run(
            KnowledgeLifecycleRepository(FakeDatabase(active_session)).delete_document(
                item.id,
                confirmation=item.title,
            )
        )

    item.current_published_version_id = uuid4()
    session = FakeSession([[item], []])
    scope = asyncio.run(
        KnowledgeLifecycleRepository(FakeDatabase(session)).delete_document(
            item.id,
            confirmation=item.title,
        )
    )

    assert scope is not None and scope.project_id == item.project_id
    assert item.current_published_version_id is None
    assert session.flush_count == 1
    assert session.deleted == [item]
    assert session.commit_count == 1
