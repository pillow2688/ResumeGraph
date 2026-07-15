import asyncio
import json
from uuid import UUID, uuid4

import pytest

from app.infrastructure.chat import ChatProviderError
from app.repositories.access_grant import RequestQuotaRecord
from app.schemas.access_grant import ProjectSummary, RecruiterPrincipal
from app.services.interview import (
    INSUFFICIENT_EVIDENCE_ANSWER,
    InterviewOutputInvalidError,
    InterviewProjectScopeError,
    InterviewQuotaExhaustedError,
    InterviewService,
    InterviewUnavailableError,
)
from app.services.retrieval import Evidence, RetrievalService


class FakeQuotaRepository:
    def __init__(self, result: RequestQuotaRecord | None = None) -> None:
        self.result = result or RequestQuotaRecord(request_count=1, max_requests=20)
        self.calls: list[UUID] = []

    async def consume_request(self, grant_id: UUID) -> RequestQuotaRecord | None:
        self.calls.append(grant_id)
        return self.result


class FakeRetrievalService:
    resolve_project_scope = staticmethod(RetrievalService.resolve_project_scope)

    def __init__(self, evidence: list[Evidence]) -> None:
        self.evidence = evidence
        self.retrieve_calls: list[dict[str, object]] = []
        self.revalidate_calls: list[dict[str, object]] = []
        self.valid_handles = {item.citation_handle for item in evidence}

    async def retrieve(self, **kwargs: object) -> list[Evidence]:
        self.retrieve_calls.append(kwargs)
        return self.evidence

    async def revalidate(self, **kwargs: object) -> set[str]:
        self.revalidate_calls.append(kwargs)
        return self.valid_handles


class FakeChatProvider:
    provider_name = "deepseek"
    model_name = "deepseek-v4-pro"

    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, str]] = []

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, str)
        return outcome


def make_principal() -> RecruiterPrincipal:
    first, second = uuid4(), uuid4()
    return RecruiterPrincipal(
        grant_id=uuid4(),
        grant_name="Fictional Interview",
        allowed_project_ids=[first, second],
        grant_expires_at="2026-07-30T10:00:00Z",
        remaining_requests=20,
        allowed_projects=[
            ProjectSummary(id=first, name="候选人简历与个人背景"),
            ProjectSummary(id=second, name="ResumeGraph"),
        ],
    )


def make_evidence(
    *,
    document_scope: str = "project",
    project_id: UUID | None = None,
    project_name: str | None = "ResumeGraph",
) -> Evidence:
    return Evidence(
        citation_handle="evidence_1",
        chunk_id=uuid4(),
        content="我在 ResumeGraph 中使用 Redis 保存短期 Session 和限流计数。",
        content_hash="a" * 64,
        document_scope=document_scope,
        project_id=(
            None
            if document_scope == "profile"
            else project_id
            if project_id is not None
            else uuid4()
        ),
        project_name=project_name,
        document_id=uuid4(),
        document_title="项目设计文档",
        version_number=1,
        heading_path=("状态管理", "Redis"),
        distance=0.15,
    )


def answered(*handles: str) -> str:
    return json.dumps(
        {
            "status": "answered",
            "answer": "我使用 Redis 保存短期 Session 和限流计数。",
            "citation_handles": list(handles),
        },
        ensure_ascii=False,
    )


def make_service(
    *,
    quota: FakeQuotaRepository | None = None,
    retrieval: FakeRetrievalService | None = None,
    chat: FakeChatProvider | None = None,
) -> tuple[InterviewService, FakeQuotaRepository, FakeRetrievalService, FakeChatProvider]:
    actual_quota = quota or FakeQuotaRepository()
    actual_retrieval = retrieval or FakeRetrievalService([make_evidence()])
    actual_chat = chat or FakeChatProvider([answered("evidence_1")])
    return (
        InterviewService(
            actual_quota,
            actual_retrieval,
            actual_chat,
            output_retry_count=1,
            dependency_timeout_seconds=1,
        ),
        actual_quota,
        actual_retrieval,
        actual_chat,
    )


def test_scope_error_happens_before_quota_or_any_provider_call() -> None:
    service, quota, retrieval, chat = make_service()
    principal = make_principal()

    with pytest.raises(InterviewProjectScopeError):
        asyncio.run(
            service.ask(
                principal=principal,
                question="question",
                requested_project_ids=[uuid4()],
            )
        )

    assert quota.calls == []
    assert retrieval.retrieve_calls == []
    assert chat.calls == []


def test_quota_exhaustion_stops_before_embedding_and_chat() -> None:
    quota = FakeQuotaRepository()
    quota.result = None
    service, quota, retrieval, chat = make_service(quota=quota)

    with pytest.raises(InterviewQuotaExhaustedError):
        asyncio.run(
            service.ask(
                principal=make_principal(),
                question="question",
                requested_project_ids=None,
            )
        )

    assert len(quota.calls) == 1
    assert retrieval.retrieve_calls == []
    assert chat.calls == []


def test_no_evidence_still_consumes_once_and_returns_the_fixed_refusal() -> None:
    retrieval = FakeRetrievalService([])
    service, quota, retrieval, chat = make_service(retrieval=retrieval)

    result = asyncio.run(
        service.ask(
            principal=make_principal(),
            question="资料中没有的问题",
            requested_project_ids=None,
        )
    )

    assert result.status == "insufficient_evidence"
    assert result.answer == INSUFFICIENT_EVIDENCE_ANSWER
    assert result.citations == []
    assert result.remaining_requests == 19
    assert len(quota.calls) == 1
    assert len(retrieval.retrieve_calls) == 1
    assert chat.calls == []


def test_answered_response_exposes_only_valid_public_citation_metadata() -> None:
    evidence = make_evidence()
    retrieval = FakeRetrievalService([evidence])
    service, _quota, retrieval, chat = make_service(retrieval=retrieval)

    result = asyncio.run(
        service.ask(
            principal=make_principal(),
            question="为什么使用 Redis？",
            requested_project_ids=None,
        )
    )

    assert result.status == "answered"
    assert result.answer.startswith("我")
    assert result.remaining_requests == 19
    assert result.citations[0].citation_handle == "evidence_1"
    assert result.citations[0].project_id == evidence.project_id
    assert result.citations[0].document_title == "项目设计文档"
    assert not hasattr(result.citations[0], "content")
    assert not hasattr(result.citations[0], "chunk_id")
    assert len(retrieval.revalidate_calls) == 1
    prompts = chat.calls[0]
    assert "候选人的 AI 面试助手" in prompts["system_prompt"]
    assert "第一人称" in prompts["system_prompt"]
    assert "不可信" in prompts["system_prompt"]
    assert str(evidence.chunk_id) not in prompts["user_prompt"]
    assert "evidence_1" in prompts["user_prompt"]


def test_profile_answer_returns_scope_without_fabricating_project_metadata() -> None:
    evidence = make_evidence(
        document_scope="profile",
        project_id=None,
        project_name=None,
    )
    retrieval = FakeRetrievalService([evidence])
    service, _quota, _retrieval, _chat = make_service(retrieval=retrieval)

    result = asyncio.run(
        service.ask(
            principal=make_principal(),
            question="What is your education?",
            requested_project_ids=None,
        )
    )

    citation = result.citations[0]
    assert citation.document_scope == "profile"
    assert citation.project_id is None
    assert citation.project_name is None


def test_forged_citation_handle_is_retried_once_then_rejected() -> None:
    chat = FakeChatProvider([answered("forged"), answered("forged_again")])
    service, quota, _retrieval, chat = make_service(chat=chat)

    with pytest.raises(InterviewOutputInvalidError):
        asyncio.run(
            service.ask(
                principal=make_principal(),
                question="question",
                requested_project_ids=None,
            )
        )

    assert len(chat.calls) == 2
    assert len(quota.calls) == 1


def test_invalid_output_can_recover_on_the_single_regeneration() -> None:
    chat = FakeChatProvider([answered("forged"), answered("evidence_1")])
    service, _quota, _retrieval, chat = make_service(chat=chat)

    result = asyncio.run(
        service.ask(
            principal=make_principal(),
            question="question",
            requested_project_ids=None,
        )
    )

    assert result.status == "answered"
    assert len(chat.calls) == 2


def test_insufficient_model_answer_is_normalized_and_has_no_citations() -> None:
    chat = FakeChatProvider(
        [
            json.dumps(
                {
                    "status": "insufficient_evidence",
                    "answer": "different refusal",
                    "citation_handles": [],
                }
            )
        ]
    )
    service, _quota, _retrieval, _chat = make_service(chat=chat)

    result = asyncio.run(
        service.ask(
            principal=make_principal(),
            question="question",
            requested_project_ids=None,
        )
    )

    assert result.answer == INSUFFICIENT_EVIDENCE_ANSWER
    assert result.citations == []


def test_citation_that_becomes_unpublished_is_not_returned() -> None:
    retrieval = FakeRetrievalService([make_evidence()])
    retrieval.valid_handles = set()
    service, _quota, _retrieval, _chat = make_service(retrieval=retrieval)

    result = asyncio.run(
        service.ask(
            principal=make_principal(),
            question="question",
            requested_project_ids=None,
        )
    )

    assert result.status == "insufficient_evidence"
    assert result.answer == INSUFFICIENT_EVIDENCE_ANSWER
    assert result.citations == []


def test_provider_failure_is_sanitized_and_does_not_refund_the_consumed_request() -> None:
    chat = FakeChatProvider([ChatProviderError("chat_provider_unavailable")])
    service, quota, _retrieval, _chat = make_service(chat=chat)

    with pytest.raises(InterviewUnavailableError) as raised:
        asyncio.run(
            service.ask(
                principal=make_principal(),
                question="question",
                requested_project_ids=None,
            )
        )

    assert len(quota.calls) == 1
    assert "provider" not in str(raised.value).lower()
    assert "deepseek" not in str(raised.value).lower()
