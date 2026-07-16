import asyncio
import json
from uuid import uuid4

import pytest

from app.agent.schemas import (
    AgentEvidence,
    AgentName,
    FinalAnswerStatus,
    KnowledgeStatus,
    KnowledgeType,
    SupervisorAgentInput,
)
from app.agent.supervisor import InterviewSupervisorAgent
from app.agent.tools import SupervisorAgentTools


class FakeChatProvider:
    provider_name = "fake"
    model_name = "fake-chat"

    def __init__(self, payloads: list[dict[str, object] | str]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict[str, str]] = []

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        payload = self.payloads.pop(0)
        return payload if isinstance(payload, str) else json.dumps(payload)


def make_input(*, allowed: list | None = None) -> SupervisorAgentInput:
    projects = allowed or [uuid4()]
    return SupervisorAgentInput(
        question="项目怎么解决 Redis 缓存雪崩？",
        recent_messages=[],
        conversation_summary="",
        allowed_project_ids=projects,
        effective_project_ids=projects,
        active_project_ids=[],
        active_technical_topics=[],
    )


def make_evidence(handle: str = "evidence_1") -> AgentEvidence:
    project_id = uuid4()
    return AgentEvidence(
        citation_handle=handle,
        chunk_id=uuid4(),
        content="Redis stores server-side sessions.",
        content_hash="a" * 64,
        document_scope="project",
        knowledge_type="project_fact",
        knowledge_status="implemented",
        project_id=project_id,
        project_name="ResumeGraph",
        document_id=uuid4(),
        document_title="Redis usage",
        version_number=1,
        heading_path=["Redis"],
        distance=0.1,
    )


def test_supervisor_routes_with_strict_server_revalidated_project_scope() -> None:
    allowed, forbidden = uuid4(), uuid4()
    chat = FakeChatProvider(
        [
            {
                "selected_agents": ["project_agent", "technical_agent"],
                "target_project_ids": [str(allowed), str(forbidden)],
                "technical_topics": ["Redis", "Redis"],
                "needs_comparison": False,
                "response_strategy": "Combine implementation and principles.",
            }
        ]
    )
    supervisor = InterviewSupervisorAgent(
        chat,
        SupervisorAgentTools(),
        max_specialist_calls=4,
        output_retries=1,
    )

    run = asyncio.run(supervisor.route(make_input(allowed=[allowed])))

    assert run.decision.selected_agents == [AgentName.PROJECT, AgentName.TECHNICAL]
    assert run.decision.target_project_ids == [allowed]
    assert run.llm_call_count == 1
    assert str(forbidden) not in json.dumps(run.decision.model_dump(mode="json"))


def test_supervisor_draft_uses_only_registered_handles_and_flexible_status() -> None:
    evidence = make_evidence()
    chat = FakeChatProvider(
        [
            {
                "status": "answered_with_boundary",
                "answer": "我目前使用 Redis 保存 Session；缓存雪崩方案尚未落地。",
                "citation_handles": ["evidence_1", "evidence_99", "evidence_1"],
            }
        ]
    )
    supervisor = InterviewSupervisorAgent(
        chat,
        SupervisorAgentTools(),
        max_specialist_calls=4,
        output_retries=1,
    )

    run = asyncio.run(
        supervisor.draft(
            make_input(),
            agent_results={},
            evidence_registry={"evidence_1": evidence},
        )
    )

    assert run.output.status == FinalAnswerStatus.ANSWERED_WITH_BOUNDARY
    assert run.output.citation_handles == ["evidence_1"]
    assert "evidence_99" not in run.output.model_dump_json()


def test_supervisor_draft_forces_boundary_status_for_implemented_and_planned_evidence() -> None:
    implemented = make_evidence("evidence_1")
    planned = make_evidence("evidence_2").model_copy(
        update={
            "knowledge_type": KnowledgeType.PLANNED_SOLUTION,
            "knowledge_status": KnowledgeStatus.PLANNED,
        }
    )
    chat = FakeChatProvider(
        [
            {
                "status": "answered",
                "answer": "我目前使用 Redis 保存 Session，后续可以考虑检索结果缓存。",
                "citation_handles": ["evidence_1", "evidence_2"],
            }
        ]
    )
    supervisor = InterviewSupervisorAgent(
        chat,
        SupervisorAgentTools(),
        max_specialist_calls=4,
        output_retries=1,
    )

    run = asyncio.run(
        supervisor.draft(
            make_input(),
            agent_results={},
            evidence_registry={"evidence_1": implemented, "evidence_2": planned},
        )
    )

    assert run.output.status == FinalAnswerStatus.ANSWERED_WITH_BOUNDARY


def test_supervisor_cannot_answer_factual_question_without_evidence() -> None:
    chat = FakeChatProvider(
        [
            {
                "status": "answered",
                "answer": "I invented a factual answer.",
                "citation_handles": [],
            }
        ]
    )
    supervisor = InterviewSupervisorAgent(
        chat,
        SupervisorAgentTools(),
        max_specialist_calls=4,
        output_retries=1,
    )

    run = asyncio.run(supervisor.draft(make_input(), agent_results={}, evidence_registry={}))

    assert run.output.status == FinalAnswerStatus.INSUFFICIENT_EVIDENCE
    assert "invented" not in run.output.answer


def test_supervisor_structured_output_retries_only_once() -> None:
    chat = FakeChatProvider(["invalid", "invalid-again"])
    supervisor = InterviewSupervisorAgent(
        chat,
        SupervisorAgentTools(),
        max_specialist_calls=4,
        output_retries=1,
    )

    run = asyncio.run(supervisor.route(make_input()))

    assert run.decision.selected_agents == []
    assert run.llm_call_count == 2


@pytest.mark.parametrize(
    ("question", "selected_agents", "technical_topics"),
    [
        ("请介绍一下你的教育背景。", ["profile_agent"], []),
        ("请介绍 ResumeGraph 项目。", ["project_agent"], []),
        ("Redis 的缓存击穿是什么？", ["technical_agent"], ["Redis"]),
        (
            "你的项目怎么解决 Redis 缓存雪崩？",
            ["project_agent", "technical_agent"],
            ["Redis"],
        ),
    ],
)
def test_supervisor_routes_core_interview_question_types(
    question: str,
    selected_agents: list[str],
    technical_topics: list[str],
) -> None:
    project_id = uuid4()
    chat = FakeChatProvider(
        [
            {
                "selected_agents": selected_agents,
                "target_project_ids": (
                    [str(project_id)] if "project_agent" in selected_agents else []
                ),
                "technical_topics": technical_topics,
                "needs_comparison": False,
                "response_strategy": "Use the relevant bounded specialist evidence.",
            }
        ]
    )
    agent_input = make_input(allowed=[project_id]).model_copy(update={"question": question})
    supervisor = InterviewSupervisorAgent(
        chat,
        SupervisorAgentTools(),
        max_specialist_calls=4,
        output_retries=1,
    )

    run = asyncio.run(supervisor.route(agent_input))

    assert [item.value for item in run.decision.selected_agents] == selected_agents
    assert run.decision.technical_topics == technical_topics
