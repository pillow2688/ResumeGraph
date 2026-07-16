import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.agent.graph import InterviewGraphTimeoutError
from app.agent.schemas import AgentEvidence, FinalAnswerStatus
from app.core.config import Settings
from app.infrastructure.interview_conversation import InterviewConversationStore
from app.repositories.access_grant import RequestQuotaRecord
from app.schemas.access_grant import ProjectSummary, RecruiterPrincipal
from app.services.interview_workflow import (
    ConversationPreviousRequestFailedError,
    InterviewWorkflowService,
)

NOW = datetime(2026, 7, 16, 10, 0, tzinfo=UTC)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None:
        self.values[key] = value
        self.ttls[key] = ttl_seconds

    async def set_if_absent_with_ttl(self, key: str, value: str, ttl_seconds: int) -> bool:
        if key in self.values:
            return False
        self.values[key] = value
        self.ttls[key] = ttl_seconds
        return True

    async def compare_and_delete(self, key: str, expected_value: str) -> bool:
        if self.values.get(key) != expected_value:
            return False
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        return True

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.ttls.pop(key, None)

    async def increment_with_ttl(self, key: str, ttl_seconds: int) -> int:
        del key, ttl_seconds
        return 1


class FakeQuotaRepository:
    def __init__(self, remaining: int = 19) -> None:
        self.remaining = remaining
        self.calls = 0

    async def consume_request(self, grant_id: UUID) -> RequestQuotaRecord | None:
        del grant_id
        self.calls += 1
        return RequestQuotaRecord(request_count=20 - self.remaining, max_requests=20)


class FakeGraph:
    def __init__(self, project_id: UUID, *, failure: Exception | None = None) -> None:
        self.project_id = project_id
        self.failure = failure
        self.calls = 0
        self.initial_states: list[dict[str, object]] = []

    async def run(self, initial_state):
        self.calls += 1
        self.initial_states.append(initial_state)
        if self.failure is not None:
            raise self.failure
        evidence = AgentEvidence(
            citation_handle="evidence_1",
            chunk_id=uuid4(),
            content="Redis stores server-side sessions.",
            content_hash="a" * 64,
            document_scope="project",
            knowledge_type="project_fact",
            knowledge_status="implemented",
            project_id=self.project_id,
            project_name="ResumeGraph",
            document_id=uuid4(),
            document_title="Redis usage",
            version_number=1,
            heading_path=["Redis"],
            distance=0.1,
        )
        return {
            **initial_state,
            "final_status": FinalAnswerStatus.ANSWERED,
            "final_answer": "我使用 Redis 保存服务端 Session。",
            "citations": ["evidence_1"],
            "evidence_registry": {"evidence_1": evidence},
            "active_project_ids": [self.project_id],
            "active_technical_topics": ["Redis"],
            "agents_used": ["project_agent", "verification_agent"],
            "public_path": ["查询项目资料", "验证回答"],
            "graph_step_count": 5,
            "llm_call_count": 4,
            "tool_call_count": 6,
            "repair_count": 0,
        }


class BlockingGraph:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run(self, initial_state):
        del initial_state
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def principal(project_id: UUID, *, remaining: int = 20) -> RecruiterPrincipal:
    return RecruiterPrincipal(
        grant_id=uuid4(),
        grant_name="Fictional interview grant",
        allowed_project_ids=[project_id],
        grant_expires_at=NOW + timedelta(hours=2),
        remaining_requests=remaining,
        allowed_projects=[ProjectSummary(id=project_id, name="ResumeGraph")],
    )


def settings() -> Settings:
    return Settings(environment="test", cookie_secure=False, _env_file=None)


def make_service(project_id: UUID, graph: FakeGraph, quota: FakeQuotaRepository):
    store = InterviewConversationStore(FakeRedis(), max_turns=8, clock=lambda: NOW)
    service = InterviewWorkflowService(
        quota,
        store,
        retrieval_service=object(),
        chat_provider=object(),
        settings=settings(),
        graph_factory=lambda _principal, _scope, _sink: graph,
        clock=lambda: NOW,
    )
    return service, store


def test_create_ask_and_duplicate_request_charge_and_run_only_once() -> None:
    project_id = uuid4()
    graph = FakeGraph(project_id)
    quota = FakeQuotaRepository(remaining=19)
    service, store = make_service(project_id, graph, quota)
    recruiter = principal(project_id)
    created = asyncio.run(
        service.create_conversation(principal=recruiter, session_token="owner-session")
    )
    request_id = uuid4()

    first = asyncio.run(
        service.ask(
            principal=recruiter,
            session_token="owner-session",
            conversation_id=created.conversation_id,
            request_id=request_id,
            question="为什么项目使用 Redis？",
            requested_project_ids=[project_id],
        )
    )
    duplicate = asyncio.run(
        service.ask(
            principal=recruiter,
            session_token="owner-session",
            conversation_id=created.conversation_id,
            request_id=request_id,
            question="为什么项目使用 Redis？",
            requested_project_ids=[project_id],
        )
    )

    assert first == duplicate
    assert first.remaining_requests == 19
    assert first.citations[0].document_title == "Redis usage"
    assert first.citations[0].excerpt == "Redis stores server-side sessions."
    assert first.agent_trace.agents_used == ["project_agent", "verification_agent"]
    assert quota.calls == 1
    assert graph.calls == 1
    conversation = asyncio.run(
        store.read_owned(
            created.conversation_id,
            session_token="owner-session",
            grant_id=recruiter.grant_id,
        )
    )
    assert conversation is not None
    assert len(conversation.recent_turns) == 1
    assert "evidence_registry" not in conversation.model_dump()
    assert graph.initial_states[0]["evidence_registry"] == {}


def test_unopened_project_returns_natural_boundary_without_charging() -> None:
    project_id = uuid4()
    graph = FakeGraph(project_id)
    quota = FakeQuotaRepository()
    service, _store = make_service(project_id, graph, quota)
    recruiter = principal(project_id)
    created = asyncio.run(
        service.create_conversation(principal=recruiter, session_token="owner-session")
    )

    response = asyncio.run(
        service.ask(
            principal=recruiter,
            session_token="owner-session",
            conversation_id=created.conversation_id,
            request_id=uuid4(),
            question="介绍未开放项目",
            requested_project_ids=[uuid4()],
        )
    )

    assert response.status is FinalAnswerStatus.ACCESS_RESTRICTED
    assert "没有开放" in response.answer
    assert quota.calls == 0
    assert graph.calls == 0


def test_provider_failure_is_not_refunded_or_recharged_for_same_request_id() -> None:
    project_id = uuid4()
    graph = FakeGraph(project_id, failure=InterviewGraphTimeoutError())
    quota = FakeQuotaRepository()
    service, _store = make_service(project_id, graph, quota)
    recruiter = principal(project_id)
    created = asyncio.run(
        service.create_conversation(principal=recruiter, session_token="owner-session")
    )
    request_id = uuid4()

    with pytest.raises(Exception, match="temporarily unavailable"):
        asyncio.run(
            service.ask(
                principal=recruiter,
                session_token="owner-session",
                conversation_id=created.conversation_id,
                request_id=request_id,
                question="Why Redis?",
                requested_project_ids=None,
            )
        )
    with pytest.raises(ConversationPreviousRequestFailedError):
        asyncio.run(
            service.ask(
                principal=recruiter,
                session_token="owner-session",
                conversation_id=created.conversation_id,
                request_id=request_id,
                question="Why Redis?",
                requested_project_ids=None,
            )
        )

    assert quota.calls == 1
    assert graph.calls == 1


def test_recent_turn_summaries_help_pronoun_resolution_but_never_become_evidence() -> None:
    project_id = uuid4()
    graph = FakeGraph(project_id)
    quota = FakeQuotaRepository(remaining=18)
    service, _store = make_service(project_id, graph, quota)
    recruiter = principal(project_id)
    created = asyncio.run(
        service.create_conversation(principal=recruiter, session_token="owner-session")
    )

    asyncio.run(
        service.ask(
            principal=recruiter,
            session_token="owner-session",
            conversation_id=created.conversation_id,
            request_id=uuid4(),
            question="为什么使用 Redis？",
            requested_project_ids=[project_id],
        )
    )
    asyncio.run(
        service.ask(
            principal=recruiter,
            session_token="owner-session",
            conversation_id=created.conversation_id,
            request_id=uuid4(),
            question="那为什么不用本地内存？",
            requested_project_ids=[project_id],
        )
    )

    second = graph.initial_states[1]
    assert second["recent_messages"] == [
        {"role": "user", "summary": "为什么使用 Redis？"},
        {"role": "assistant", "summary": "我使用 Redis 保存服务端 Session。"},
    ]
    assert second["evidence_registry"] == {}


def test_cancelled_stream_marks_request_failed_and_releases_conversation_lock() -> None:
    async def scenario() -> None:
        project_id = uuid4()
        graph = BlockingGraph()
        quota = FakeQuotaRepository()
        service, store = make_service(project_id, graph, quota)  # type: ignore[arg-type]
        recruiter = principal(project_id)
        created = await service.create_conversation(
            principal=recruiter,
            session_token="owner-session",
        )
        request_id = uuid4()
        task = asyncio.create_task(
            service.ask(
                principal=recruiter,
                session_token="owner-session",
                conversation_id=created.conversation_id,
                request_id=request_id,
                question="为什么使用 Redis？",
                requested_project_ids=[project_id],
            )
        )
        await graph.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        request = await store.read_request(created.conversation_id, request_id)
        assert request is not None
        assert request.status.value == "failed"
        next_lock = await store.acquire_turn_lock(created.conversation_id, ttl_seconds=30)
        assert next_lock is not None
        assert quota.calls == 1

    asyncio.run(scenario())
