import asyncio
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from app.infrastructure.embedding import FakeEmbeddingProvider
from app.repositories.retrieval import RetrievalRecord
from app.services.retrieval import EmptyProjectScopeError, RetrievalService


class FakeRepository:
    def __init__(self, records: list[RetrievalRecord]) -> None:
        self.records = records
        self.calls: list[dict[str, object]] = []

    async def search(self, **kwargs: object) -> list[RetrievalRecord]:
        self.calls.append(kwargs)
        return self.records

    async def revalidate(self, **kwargs: object) -> set[UUID]:
        chunk_ids = kwargs["chunk_ids"]
        assert isinstance(chunk_ids, list)
        return set(chunk_ids)


def make_record(
    *,
    content: str = "PostgreSQL is the authorization source of truth.",
    content_hash: str = "a" * 64,
    distance: float = 0.2,
    document_scope: str = "project",
    project_id: UUID | None = None,
    project_name: str | None = "ResumeGraph",
    knowledge_status: str | None = None,
) -> RetrievalRecord:
    return RetrievalRecord(
        chunk_id=uuid4(),
        content=content,
        content_hash=content_hash,
        document_scope=document_scope,
        knowledge_status=knowledge_status
        or ("general_knowledge" if document_scope == "technical" else "implemented"),
        project_id=(
            None
            if document_scope in {"profile", "technical"}
            else project_id
            if project_id is not None
            else uuid4()
        ),
        project_name=project_name,
        document_id=uuid4(),
        document_title="Architecture",
        version_number=1,
        heading_path=("Security",),
        distance=distance,
    )


def make_service(repository: FakeRepository, *, max_context_characters: int = 12_000):
    return RetrievalService(
        repository,
        FakeEmbeddingProvider(
            provider_name="zhipu",
            model_name="embedding-3",
            dimensions=4,
        ),
        top_k=6,
        max_context_characters=max_context_characters,
        dependency_timeout_seconds=1,
    )


def test_project_scope_defaults_to_all_allowed_projects() -> None:
    allowed = [uuid4(), uuid4()]

    assert RetrievalService.resolve_project_scope(allowed, None) == allowed


def test_requested_project_scope_uses_only_the_allowed_intersection() -> None:
    first, second, forbidden = uuid4(), uuid4(), uuid4()

    effective = RetrievalService.resolve_project_scope(
        [first, second],
        [forbidden, second, second],
    )

    assert effective == [second]


@pytest.mark.parametrize("requested", [[], [uuid4()]])
def test_empty_effective_scope_is_an_error_and_never_falls_back(requested: list[UUID]) -> None:
    with pytest.raises(EmptyProjectScopeError):
        RetrievalService.resolve_project_scope([uuid4()], requested)


def test_retrieve_embeds_once_and_passes_active_identity_and_scope_to_repository() -> None:
    record = make_record()
    repository = FakeRepository([record])
    service = make_service(repository)
    grant_id, project_id = uuid4(), uuid4()

    evidence = asyncio.run(
        service.retrieve(
            query="Why PostgreSQL?",
            grant_id=grant_id,
            project_ids=[project_id],
        )
    )

    assert evidence[0].citation_handle == "evidence_1"
    assert evidence[0].chunk_id == record.chunk_id
    call = repository.calls[0]
    assert call["grant_id"] == grant_id
    assert call["project_ids"] == [project_id]
    assert call["provider_name"] == "zhipu"
    assert call["model_name"] == "embedding-3"
    assert call["dimensions"] == 4
    assert call["top_k"] == 6
    assert len(call["query_embedding"]) == 4


def test_retrieve_preserves_profile_scope_without_project_identity() -> None:
    record = make_record(
        document_scope="profile",
        project_id=None,
        project_name=None,
    )
    service = make_service(FakeRepository([record]))

    evidence = asyncio.run(
        service.retrieve(query="education", grant_id=uuid4(), project_ids=[uuid4()])
    )

    assert evidence[0].document_scope == "profile"
    assert evidence[0].project_id is None
    assert evidence[0].project_name is None
    assert evidence[0].knowledge_type == "profile_fact"
    assert evidence[0].knowledge_status == "implemented"


def test_specialist_searches_use_strict_scope_and_deterministic_knowledge_type() -> None:
    profile = make_record(document_scope="profile", project_name=None)
    project = make_record(knowledge_status="planned")
    technical = make_record(
        document_scope="technical",
        project_name=None,
        knowledge_status="general_knowledge",
    )
    repository = FakeRepository([profile])
    service = make_service(repository)
    grant_id, project_id = uuid4(), uuid4()

    profile_evidence = asyncio.run(
        service.search_profile_knowledge(query="education", grant_id=grant_id)
    )
    repository.records = [project]
    project_evidence = asyncio.run(
        service.search_project_knowledge(
            query="future cache",
            grant_id=grant_id,
            project_ids=[project_id],
        )
    )
    repository.records = [technical]
    technical_evidence = asyncio.run(
        service.search_technical_knowledge(query="cache avalanche", grant_id=grant_id)
    )

    assert [call["retrieval_scope"] for call in repository.calls] == [
        "profile",
        "project",
        "technical",
    ]
    assert repository.calls[0]["project_ids"] == []
    assert repository.calls[1]["project_ids"] == [project_id]
    assert repository.calls[2]["project_ids"] == []
    assert profile_evidence[0].knowledge_type == "profile_fact"
    assert project_evidence[0].knowledge_type == "planned_solution"
    assert technical_evidence[0].knowledge_type == "technical_knowledge"


def test_phase_3_retrieve_does_not_expand_into_technical_scope() -> None:
    repository = FakeRepository([])
    service = make_service(repository)

    asyncio.run(service.retrieve(query="Redis", grant_id=uuid4(), project_ids=[uuid4()]))

    assert repository.calls[0]["retrieval_scope"] == "interview"


def test_retrieve_deduplicates_content_hash_then_assigns_stable_handles() -> None:
    first = make_record(content_hash="a" * 64, distance=0.1)
    duplicate = replace(first, chunk_id=uuid4(), distance=0.15)
    second = make_record(content_hash="b" * 64, distance=0.2)
    service = make_service(FakeRepository([first, duplicate, second]))

    evidence = asyncio.run(
        service.retrieve(query="question", grant_id=uuid4(), project_ids=[uuid4()])
    )

    assert [item.chunk_id for item in evidence] == [first.chunk_id, second.chunk_id]
    assert [item.citation_handle for item in evidence] == ["evidence_1", "evidence_2"]


def test_retrieve_keeps_only_complete_chunks_inside_the_character_budget() -> None:
    first = make_record(content="12345", content_hash="a" * 64)
    too_large = make_record(content="123456", content_hash="b" * 64)
    later = make_record(content="1234", content_hash="c" * 64)
    service = make_service(
        FakeRepository([first, too_large, later]),
        max_context_characters=9,
    )

    evidence = asyncio.run(
        service.retrieve(query="question", grant_id=uuid4(), project_ids=[uuid4()])
    )

    assert [item.chunk_id for item in evidence] == [first.chunk_id, later.chunk_id]


def test_revalidate_returns_only_handles_whose_chunks_remain_published_and_authorized() -> None:
    first, second = make_record(), make_record(content_hash="b" * 64)
    repository = FakeRepository([first, second])
    service = make_service(repository)
    evidence = asyncio.run(
        service.retrieve(query="question", grant_id=uuid4(), project_ids=[uuid4()])
    )
    repository.revalidate = lambda **_kwargs: _return_set({first.chunk_id})  # type: ignore[method-assign]

    valid = asyncio.run(
        service.revalidate(
            grant_id=uuid4(),
            project_ids=[uuid4()],
            evidence=evidence,
        )
    )

    assert valid == {"evidence_1"}


async def _return_set(value: set[UUID]) -> set[UUID]:
    return value
