import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

from app.repositories.deduplication import DeduplicationRepository, DeduplicationScope


class FakeResult:
    def all(self) -> list[object]:
        return []


class FakeSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement: object) -> FakeResult:
        self.statements.append(statement)
        return FakeResult()


class FakeDatabase:
    def __init__(self) -> None:
        self.session_instance = FakeSession()

    @asynccontextmanager
    async def session(self):
        yield self.session_instance


def test_profile_load_is_current_published_hash_safe_and_includes_only_auto_duplicates() -> None:
    database = FakeDatabase()
    repository = DeduplicationRepository(database)

    snapshot = asyncio.run(
        repository.load_scope(
            DeduplicationScope(scope="profile"),
            provider_name="zhipu",
            model_name="embedding-3",
            dimensions=1024,
        )
    )

    assert snapshot.candidates == ()
    assert len(database.session_instance.statements) == 2
    revision_sql = str(
        database.session_instance.statements[0].compile(compile_kwargs={"literal_binds": True})
    )
    assert "knowledge_documents.document_scope = 'profile'" in revision_sql
    statement = database.session_instance.statements[1]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "knowledge_documents.document_scope = 'profile'" in sql
    assert "knowledge_documents.current_published_version_id = document_versions.id" in sql
    assert "document_versions.status = 'published'" in sql
    assert "document_chunks.enabled IS true" in sql
    assert "document_chunks.disabled_reason = 'exact_duplicate'" in sql
    assert "chunk_embeddings.provider_name = 'zhipu'" in sql
    assert "chunk_embeddings.model_name = 'embedding-3'" in sql
    assert "chunk_embeddings.dimensions = 1024" in sql
    assert "chunk_embeddings.content_hash = document_chunks.content_hash" in sql
    assert "duplicate_of" not in sql


def test_project_load_requires_one_explicit_project_scope() -> None:
    database = FakeDatabase()
    repository = DeduplicationRepository(database)
    project_id = uuid4()

    asyncio.run(
        repository.load_scope(
            DeduplicationScope(scope="project", project_id=project_id),
            provider_name="zhipu",
            model_name="embedding-3",
            dimensions=1024,
        )
    )

    sql = str(
        database.session_instance.statements[1].compile(compile_kwargs={"literal_binds": True})
    )
    assert "knowledge_documents.document_scope = 'project'" in sql
    assert "knowledge_documents.project_id =" in sql
    assert project_id.hex in sql
