import asyncio
from uuid import uuid4

import pytest

from app.repositories.knowledge_lifecycle import (
    ActiveDocumentJobRepositoryError,
    DocumentConfirmationRepositoryError,
    LifecycleScopeRecord,
    VersionNotDeletableRepositoryError,
)
from app.services.knowledge_lifecycle import (
    ActiveDocumentJobError,
    DocumentConfirmationError,
    KnowledgeLifecycleService,
    VersionNotDeletableError,
)


class FakeRepository:
    def __init__(self) -> None:
        self.result: LifecycleScopeRecord | None = None
        self.failure: Exception | None = None
        self.version_calls: list[object] = []
        self.document_calls: list[tuple[object, str]] = []

    async def delete_version(self, version_id):
        self.version_calls.append(version_id)
        if self.failure is not None:
            raise self.failure
        return self.result

    async def delete_document(self, document_id, *, confirmation: str):
        self.document_calls.append((document_id, confirmation))
        if self.failure is not None:
            raise self.failure
        return self.result


class FakeDeduplicationService:
    def __init__(self) -> None:
        self.profile_calls = 0
        self.project_calls: list[object] = []

    async def rebuild_profile_scope(self):
        self.profile_calls += 1

    async def rebuild_project_scope(self, project_id):
        self.project_calls.append(project_id)


def test_version_and_document_delete_rebuild_the_affected_scope() -> None:
    repository = FakeRepository()
    deduplication = FakeDeduplicationService()
    service = KnowledgeLifecycleService(
        repository,
        deduplication,
        dependency_timeout_seconds=1,
    )
    version_id = uuid4()
    repository.result = LifecycleScopeRecord(document_scope="profile", project_id=None)

    asyncio.run(service.delete_version(version_id))

    project_id = uuid4()
    document_id = uuid4()
    repository.result = LifecycleScopeRecord(document_scope="project", project_id=project_id)
    asyncio.run(service.delete_document(document_id, confirmation="Fictional resume"))

    assert repository.version_calls == [version_id]
    assert repository.document_calls == [(document_id, "Fictional resume")]
    assert deduplication.profile_calls == 1
    assert deduplication.project_calls == [project_id]


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (VersionNotDeletableRepositoryError(), VersionNotDeletableError),
        (ActiveDocumentJobRepositoryError(), ActiveDocumentJobError),
        (DocumentConfirmationRepositoryError(), DocumentConfirmationError),
    ],
)
def test_lifecycle_service_translates_safe_conflicts(
    failure: Exception,
    expected: type[Exception],
) -> None:
    repository = FakeRepository()
    repository.failure = failure
    service = KnowledgeLifecycleService(
        repository,
        FakeDeduplicationService(),
        dependency_timeout_seconds=1,
    )

    with pytest.raises(expected):
        asyncio.run(service.delete_document(uuid4(), confirmation="Fictional resume"))
