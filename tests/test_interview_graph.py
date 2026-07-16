import asyncio
import json
from uuid import uuid4

from app.agent.graph import InterviewGraph, initial_interview_state
from app.agent.profile_agent import ProfileAgent
from app.agent.project_agent import ProjectAgent
from app.agent.schemas import FinalAnswerStatus
from app.agent.supervisor import InterviewSupervisorAgent
from app.agent.technical_agent import TechnicalAgent
from app.agent.tools import (
    ProfileAgentTools,
    ProjectAgentTools,
    SupervisorAgentTools,
    TechnicalAgentTools,
    VerificationAgentTools,
)
from app.agent.verification_agent import VerificationAgent
from app.services.retrieval import Evidence


class FakeChatProvider:
    provider_name = "fake"
    model_name = "fake-chat"

    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = list(payloads)

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        return json.dumps(self.payloads.pop(0))


def evidence(
    *,
    content_hash: str,
    scope: str,
    knowledge_status: str,
    knowledge_type: str,
    project_id=None,
) -> Evidence:
    return Evidence(
        citation_handle="evidence_1",
        chunk_id=uuid4(),
        content="Fictional published graph evidence.",
        content_hash=content_hash,
        document_scope=scope,
        knowledge_status=knowledge_status,
        knowledge_type=knowledge_type,
        project_id=project_id,
        project_name="ResumeGraph" if project_id else None,
        document_id=uuid4(),
        document_title="Graph test",
        version_number=1,
        heading_path=("Redis",),
        distance=0.1,
    )


class FakeRetrieval:
    def __init__(self, project_id) -> None:
        self.project = [
            evidence(
                content_hash="a" * 64,
                scope="project",
                knowledge_status="implemented",
                knowledge_type="project_fact",
                project_id=project_id,
            ),
            evidence(
                content_hash="b" * 64,
                scope="project",
                knowledge_status="planned",
                knowledge_type="planned_solution",
                project_id=project_id,
            ),
        ]
        self.technical = [
            evidence(
                content_hash="c" * 64,
                scope="technical",
                knowledge_status="general_knowledge",
                knowledge_type="technical_knowledge",
            )
        ]

    async def search_profile_knowledge(self, **_kwargs: object) -> list[Evidence]:
        return []

    async def search_project_knowledge(self, **_kwargs: object) -> list[Evidence]:
        return self.project

    async def search_technical_knowledge(self, **_kwargs: object) -> list[Evidence]:
        return self.technical

    async def revalidate(self, **kwargs: object) -> set[str]:
        items = kwargs["evidence"]
        assert isinstance(items, list)
        return {item.citation_handle for item in items}


def test_langgraph_runs_mixed_question_verification_and_one_repair() -> None:
    project_id, grant_id = uuid4(), uuid4()
    streamed_events: list[dict[str, object]] = []

    async def event_sink(event: dict[str, object]) -> None:
        streamed_events.append(event)

    retrieval = FakeRetrieval(project_id)
    chat = FakeChatProvider(
        [
            {
                "selected_agents": ["project_agent", "technical_agent"],
                "target_project_ids": [str(project_id)],
                "technical_topics": ["Redis"],
                "needs_comparison": False,
                "response_strategy": "Current facts, boundary, principles, future plan.",
            },
            {
                "action": "tool_call",
                "tool_name": "search_project_knowledge",
                "query": "Redis cache avalanche",
                "project_ids": [str(project_id)],
                "factual_summary": None,
                "citation_handles": [],
                "missing_points": [],
            },
            {
                "action": "finish",
                "tool_name": None,
                "query": None,
                "project_ids": [],
                "factual_summary": "Redis currently stores sessions; result caching is planned.",
                "citation_handles": ["evidence_1", "evidence_2"],
                "missing_points": [],
            },
            {
                "action": "tool_call",
                "tool_name": "search_technical_knowledge",
                "query": "cache avalanche",
                "factual_summary": None,
                "citation_handles": [],
                "missing_points": [],
            },
            {
                "action": "finish",
                "tool_name": None,
                "query": None,
                "factual_summary": "TTL randomization is a general mitigation.",
                "citation_handles": ["evidence_1"],
                "missing_points": [],
            },
            {
                "status": "answered",
                "answer": "我已经通过 TTL 随机化解决了缓存雪崩。",
                "citation_handles": ["evidence_1", "evidence_3"],
            },
            {
                "passed": False,
                "unsupported_claims": [],
                "boundary_violations": ["General knowledge was stated as implemented."],
                "invalid_citation_handles": [],
                "repair_instruction": "State the current boundary and future option.",
            },
            {
                "status": "answered_with_boundary",
                "answer": (
                    "我目前使用 Redis 管理 Session，尚未使用大规模业务查询缓存；"
                    "从技术原理上看可采用 TTL 随机化，后续缓存检索结果时会考虑该方案。"
                ),
                "citation_handles": ["evidence_1", "evidence_2", "evidence_3"],
            },
            {
                "passed": True,
                "unsupported_claims": [],
                "boundary_violations": [],
                "invalid_citation_handles": [],
                "repair_instruction": "",
            },
        ]
    )
    profile = ProfileAgent(
        chat,
        ProfileAgentTools(retrieval, grant_id=grant_id),
        max_tool_calls=2,
        output_retries=1,
    )
    project = ProjectAgent(
        chat,
        ProjectAgentTools(
            retrieval,
            grant_id=grant_id,
            effective_project_ids=[project_id],
            authorized_projects={project_id: "ResumeGraph"},
        ),
        max_tool_calls=2,
        output_retries=1,
    )
    technical = TechnicalAgent(
        chat,
        TechnicalAgentTools(retrieval, grant_id=grant_id),
        max_tool_calls=2,
        output_retries=1,
    )
    verification = VerificationAgent(
        chat,
        VerificationAgentTools(
            retrieval,
            grant_id=grant_id,
            allowed_project_ids=[project_id],
            effective_project_ids=[project_id],
        ),
        output_retries=1,
    )
    tools = SupervisorAgentTools(
        profile_runner=profile.run,
        project_runner=project.run,
        technical_runner=technical.run,
        verification_runner=verification.run,
    )
    supervisor = InterviewSupervisorAgent(
        chat,
        tools,
        max_specialist_calls=4,
        output_retries=1,
    )
    graph = InterviewGraph(
        supervisor,
        max_verification_runs=2,
        max_answer_repairs=1,
        max_graph_steps=12,
        timeout_seconds=10,
        event_sink=event_sink,
    )
    initial = initial_interview_state(
        run_id=uuid4(),
        conversation_id=uuid4(),
        recruiter_session_id="hashed-session-fingerprint",
        grant_id=grant_id,
        allowed_project_ids=[project_id],
        effective_project_ids=[project_id],
        question="你的项目怎么解决 Redis 缓存雪崩？",
        recent_messages=[],
        conversation_summary="",
        remaining_requests=19,
    )

    result = asyncio.run(graph.run(initial))

    assert result["final_status"] == FinalAnswerStatus.ANSWERED_WITH_BOUNDARY
    assert result["repair_count"] == 1
    assert result["verification_run_count"] == 2
    assert result["graph_step_count"] == 7
    assert set(result["evidence_registry"]) == {"evidence_1", "evidence_2", "evidence_3"}
    assert result["citations"] == ["evidence_1", "evidence_2", "evidence_3"]
    assert result["agents_used"] == [
        "project_agent",
        "technical_agent",
        "verification_agent",
    ]
    event_types = [event["event_type"] for event in result["public_events"]]
    assert event_types[0] == "question_received"
    assert event_types[-1] == "answer_completed"
    assert "answer_repairing" in event_types
    assert [event["event_type"] for event in streamed_events] == event_types
    assert graph.compiled_graph.get_graph().nodes


def test_graph_budget_prevents_answer_repair_when_steps_are_insufficient() -> None:
    assert InterviewGraph.can_repair(
        graph_step_count=4,
        max_graph_steps=7,
        repair_count=0,
        max_answer_repairs=1,
        verification_run_count=1,
        max_verification_runs=2,
    )
    assert not InterviewGraph.can_repair(
        graph_step_count=4,
        max_graph_steps=6,
        repair_count=0,
        max_answer_repairs=1,
        verification_run_count=1,
        max_verification_runs=2,
    )
