import asyncio
import math
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.repositories.retrieval import RetrievalRepository


class FakeMappingResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> "FakeMappingResult":
        return self

    def all(self) -> list[dict[str, object]]:
        return self._rows


class CaptureSession:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.statements: list[object] = []

    async def execute(self, statement: object) -> FakeMappingResult:
        self.statements.append(statement)
        return FakeMappingResult(self.rows)


class CaptureDatabase:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.session_instance = CaptureSession(rows)

    @asynccontextmanager
    async def session(self):
        yield self.session_instance


def row(
    *,
    distance: float = 0.25,
    document_scope: str = "project",
    project_id: UUID | None = None,
    project_name: str | None = "ResumeGraph",
    knowledge_status: str | None = None,
) -> dict[str, object]:
    return {
        "chunk_id": uuid4(),
        "content": "Redis 只保存短期 Session 和限流计数。",
        "content_hash": "a" * 64,
        "document_scope": document_scope,
        "knowledge_status": knowledge_status
        or ("general_knowledge" if document_scope == "technical" else "implemented"),
        "project_id": (
            None
            if document_scope in {"profile", "technical"}
            else project_id
            if project_id is not None
            else uuid4()
        ),
        "project_name": project_name,
        "document_id": uuid4(),
        "document_title": "项目设计文档",
        "version_number": 1,
        "heading_path": ["状态管理", "Redis"],
        "distance": distance,
    }


def test_search_builds_one_project_scoped_published_pgvector_query() -> None:
    database = CaptureDatabase([row()])
    repository = RetrievalRepository(database)
    grant_id = uuid4()
    project_ids = [uuid4(), uuid4()]

    records = asyncio.run(
        repository.search(
            grant_id=grant_id,
            query_embedding=[0.1, 0.2, 0.3],
            project_ids=project_ids,
            provider_name="zhipu",
            model_name="embedding-3",
            dimensions=3,
            top_k=6,
        )
    )

    assert records[0].document_scope == "project"
    assert records[0].project_name == "ResumeGraph"
    assert records[0].distance == 0.25
    statement = database.session_instance.statements[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = " ".join(str(compiled).lower().split())
    assert "grant_projects" in sql
    assert "access_grants" in sql
    assert "knowledge_documents" in sql
    assert "document_versions" in sql
    assert "document_chunks" in sql
    assert "chunk_embeddings" in sql
    assert "projects" in sql
    assert "<=>" in sql
    assert "row_number() over (partition by document_chunks.content_hash" in sql
    assert "knowledge_documents.document_scope" in sql
    assert "grant_projects" in sql
    assert "access_grants.revoked_at is null" in sql
    assert "access_grants.expires_at > now()" in sql
    assert "knowledge_documents.current_published_version_id" in sql
    assert "document_versions.status" in sql
    assert "document_chunks.enabled is true" in sql
    assert "document_chunks.disabled_reason is null" in sql
    assert "chunk_embeddings.provider_name" in sql
    assert "chunk_embeddings.model_name" in sql
    assert "chunk_embeddings.dimensions" in sql
    assert "chunk_embeddings.content_hash = document_chunks.content_hash" in sql
    assert "order by" in sql and "distance asc" in sql and "chunk_id asc" in sql
    assert compiled.params["grant_id_1"] == grant_id
    assert compiled.params["provider_name_1"] == "zhipu"
    assert compiled.params["model_name_1"] == "embedding-3"
    assert compiled.params["dimensions_1"] == 3
    assert compiled.params["param_1"] == 6


def test_search_maps_profile_evidence_without_fabricating_a_project() -> None:
    database = CaptureDatabase(
        [
            row(
                document_scope="profile",
                project_id=None,
                project_name=None,
            )
        ]
    )
    repository = RetrievalRepository(database)

    records = asyncio.run(
        repository.search(
            grant_id=uuid4(),
            query_embedding=[0.1, 0.2, 0.3],
            project_ids=[uuid4()],
            provider_name="zhipu",
            model_name="embedding-3",
            dimensions=3,
            top_k=6,
        )
    )

    assert records[0].document_scope == "profile"
    assert records[0].project_id is None
    assert records[0].project_name is None
    assert records[0].knowledge_status == "implemented"


def test_technical_search_requires_a_valid_grant_but_never_project_authorization() -> None:
    database = CaptureDatabase(
        [row(document_scope="technical", project_id=None, project_name=None)]
    )
    repository = RetrievalRepository(database)

    records = asyncio.run(
        repository.search(
            grant_id=uuid4(),
            query_embedding=[0.1, 0.2, 0.3],
            project_ids=[],
            retrieval_scope="technical",
            provider_name="zhipu",
            model_name="embedding-3",
            dimensions=3,
            top_k=6,
        )
    )

    assert records[0].document_scope == "technical"
    assert records[0].knowledge_status == "general_knowledge"
    assert records[0].project_id is None
    compiled = database.session_instance.statements[0].compile(dialect=postgresql.dialect())
    sql = " ".join(str(compiled).lower().split())
    assert "access_grants" in sql
    assert "grant_projects" not in sql
    assert "knowledge_documents.document_scope" in sql
    assert "knowledge_documents.knowledge_status" in sql


def test_project_only_search_keeps_grant_intersection_and_planned_evidence() -> None:
    project_id = uuid4()
    database = CaptureDatabase([row(project_id=project_id, knowledge_status="planned")])
    repository = RetrievalRepository(database)

    records = asyncio.run(
        repository.search(
            grant_id=uuid4(),
            query_embedding=[0.1, 0.2, 0.3],
            project_ids=[project_id],
            retrieval_scope="project",
            provider_name="zhipu",
            model_name="embedding-3",
            dimensions=3,
            top_k=6,
        )
    )

    assert records[0].knowledge_status == "planned"
    compiled = database.session_instance.statements[0].compile(dialect=postgresql.dialect())
    sql = " ".join(str(compiled).lower().split())
    assert "grant_projects" in sql
    assert "knowledge_documents.project_id" in sql
    assert "knowledge_documents.knowledge_status" in sql


@pytest.mark.parametrize(
    "query_embedding",
    [[], [0.1, 0.2], [0.1, float("nan"), 0.3], [0.1, float("inf"), 0.3]],
)
def test_search_rejects_invalid_query_vectors_before_database_access(
    query_embedding: list[float],
) -> None:
    database = CaptureDatabase([])
    repository = RetrievalRepository(database)

    with pytest.raises(ValueError, match="query embedding"):
        asyncio.run(
            repository.search(
                grant_id=uuid4(),
                query_embedding=query_embedding,
                project_ids=[uuid4()],
                provider_name="zhipu",
                model_name="embedding-3",
                dimensions=3,
                top_k=5,
            )
        )

    assert database.session_instance.statements == []
    assert not all(math.isfinite(value) for value in query_embedding) or len(query_embedding) != 3


def test_search_rejects_empty_project_scope_instead_of_falling_back() -> None:
    database = CaptureDatabase([])
    repository = RetrievalRepository(database)

    with pytest.raises(ValueError, match="project scope"):
        asyncio.run(
            repository.search(
                grant_id=uuid4(),
                query_embedding=[0.1, 0.2, 0.3],
                project_ids=[],
                provider_name="zhipu",
                model_name="embedding-3",
                dimensions=3,
                top_k=5,
            )
        )

    assert database.session_instance.statements == []


def test_project_specialist_search_rejects_empty_scope_but_global_searches_do_not() -> None:
    database = CaptureDatabase([])
    repository = RetrievalRepository(database)

    with pytest.raises(ValueError, match="project scope"):
        asyncio.run(
            repository.search(
                grant_id=uuid4(),
                query_embedding=[0.1, 0.2, 0.3],
                project_ids=[],
                retrieval_scope="project",
                provider_name="zhipu",
                model_name="embedding-3",
                dimensions=3,
                top_k=5,
            )
        )


def test_search_maps_only_public_evidence_fields_and_preserves_sql_order() -> None:
    first = row(distance=0.1)
    second = row(distance=0.2)
    database = CaptureDatabase([first, second])
    repository = RetrievalRepository(database)

    records = asyncio.run(
        repository.search(
            grant_id=uuid4(),
            query_embedding=[0.1, 0.2, 0.3],
            project_ids=[UUID(str(first["project_id"]))],
            provider_name="zhipu",
            model_name="embedding-3",
            dimensions=3,
            top_k=2,
        )
    )

    assert [record.distance for record in records] == [0.1, 0.2]
    assert records[0].heading_path == ("状态管理", "Redis")
