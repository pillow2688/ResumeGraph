import asyncio
import json
from uuid import UUID, uuid4

from app.agent.profile_agent import ProfileAgent
from app.agent.project_agent import ProjectAgent
from app.agent.schemas import (
    AgentResultStatus,
    ProfileAgentInput,
    ProjectAgentInput,
    TechnicalAgentInput,
)
from app.agent.technical_agent import TechnicalAgent
from app.agent.tools import ProfileAgentTools, ProjectAgentTools, TechnicalAgentTools
from app.services.retrieval import Evidence


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


def make_evidence(
    *,
    document_scope: str,
    knowledge_status: str,
    knowledge_type: str,
    project_id: UUID | None = None,
) -> Evidence:
    return Evidence(
        citation_handle="evidence_1",
        chunk_id=uuid4(),
        content="Fictional, published evidence for agent tests.",
        content_hash="a" * 64,
        document_scope=document_scope,
        knowledge_status=knowledge_status,
        knowledge_type=knowledge_type,
        project_id=project_id,
        project_name="ResumeGraph" if project_id is not None else None,
        document_id=uuid4(),
        document_title="Agent test document",
        version_number=1,
        heading_path=("Test",),
        distance=0.1,
    )


class FakeRetrievalService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.profile = [
            make_evidence(
                document_scope="profile",
                knowledge_status="implemented",
                knowledge_type="profile_fact",
            )
        ]
        self.project: list[Evidence] = []
        self.technical = [
            make_evidence(
                document_scope="technical",
                knowledge_status="general_knowledge",
                knowledge_type="technical_knowledge",
            )
        ]

    async def search_profile_knowledge(self, **kwargs: object) -> list[Evidence]:
        self.calls.append(("profile", kwargs))
        return self.profile

    async def search_project_knowledge(self, **kwargs: object) -> list[Evidence]:
        self.calls.append(("project", kwargs))
        return self.project

    async def search_technical_knowledge(self, **kwargs: object) -> list[Evidence]:
        self.calls.append(("technical", kwargs))
        return self.technical


def test_profile_agent_runs_its_own_structured_bounded_tool_loop() -> None:
    retrieval = FakeRetrievalService()
    chat = FakeChatProvider(
        [
            {
                "action": "tool_call",
                "tool_name": "search_profile_knowledge",
                "query": "education",
                "factual_summary": None,
                "citation_handles": [],
                "missing_points": [],
            },
            {
                "action": "finish",
                "tool_name": None,
                "query": None,
                "factual_summary": "我在虚构大学学习软件工程。",
                "citation_handles": ["evidence_1", "evidence_1"],
                "missing_points": [],
            },
        ]
    )
    agent = ProfileAgent(
        chat,
        ProfileAgentTools(retrieval, grant_id=uuid4()),
        max_tool_calls=2,
        output_retries=1,
    )

    run = asyncio.run(agent.run(ProfileAgentInput(question="介绍教育背景", recent_context="")))

    assert run.output.status == AgentResultStatus.FOUND
    assert run.output.citation_handles == ["evidence_1"]
    assert len(run.output.evidence) == 1
    assert run.local_state.tool_call_count == 1
    assert run.local_state.llm_call_count == 2
    assert [name for name, _kwargs in retrieval.calls] == ["profile"]
    assert all("Chain of Thought" in call["system_prompt"] for call in chat.calls)
    first_payload = json.loads(chat.calls[0]["user_prompt"])
    step_schema = first_payload["required_output_schema"]
    assert step_schema["additionalProperties"] is False
    assert {"action", "tool_name", "query"} <= set(step_schema["properties"])
    assert "tool_results is empty" in first_payload["required_action"]


def test_project_agent_intersects_model_project_ids_with_server_scope() -> None:
    retrieval = FakeRetrievalService()
    allowed, forbidden = uuid4(), uuid4()
    retrieval.project = [
        make_evidence(
            document_scope="project",
            knowledge_status="planned",
            knowledge_type="planned_solution",
            project_id=allowed,
        )
    ]
    chat = FakeChatProvider(
        [
            {
                "action": "tool_call",
                "tool_name": "search_project_knowledge",
                "query": "cache roadmap",
                "project_ids": [str(allowed), str(forbidden)],
                "factual_summary": None,
                "citation_handles": [],
                "missing_points": [],
            },
            {
                "action": "finish",
                "tool_name": None,
                "query": None,
                "project_ids": [],
                "factual_summary": "后续可以考虑缓存高频检索结果。",
                "citation_handles": ["evidence_1"],
                "missing_points": [],
            },
        ]
    )
    agent = ProjectAgent(
        chat,
        ProjectAgentTools(
            retrieval,
            grant_id=uuid4(),
            effective_project_ids=[allowed],
            authorized_projects={allowed: "ResumeGraph"},
        ),
        max_tool_calls=2,
        output_retries=1,
    )

    run = asyncio.run(
        agent.run(
            ProjectAgentInput(
                question="缓存规划是什么？",
                recent_context="",
                effective_project_ids=[allowed],
                needs_comparison=False,
            )
        )
    )

    assert run.output.status == AgentResultStatus.FOUND
    assert run.output.implemented_evidence == []
    assert len(run.output.planned_evidence) == 1
    assert retrieval.calls[0][1]["project_ids"] == [allowed]
    assert str(forbidden) not in chat.calls[-1]["user_prompt"]


def test_technical_agent_cannot_turn_general_knowledge_into_project_evidence() -> None:
    retrieval = FakeRetrievalService()
    chat = FakeChatProvider(
        [
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
                "factual_summary": "从技术原理上看，可以通过 TTL 随机化降低集中失效风险。",
                "citation_handles": ["evidence_1"],
                "missing_points": [],
            },
        ]
    )
    agent = TechnicalAgent(
        chat,
        TechnicalAgentTools(retrieval, grant_id=uuid4()),
        max_tool_calls=2,
        output_retries=1,
    )

    run = asyncio.run(
        agent.run(
            TechnicalAgentInput(
                question="缓存雪崩是什么？",
                recent_context="",
                technical_topics=["Redis"],
            )
        )
    )

    assert run.output.project_implementation_requires_project_evidence is True
    assert {item.knowledge_type.value for item in run.output.evidence} == {"technical_knowledge"}


def test_specialist_stops_when_tool_budget_is_exhausted() -> None:
    retrieval = FakeRetrievalService()
    repeated_tool_call = {
        "action": "tool_call",
        "tool_name": "search_profile_knowledge",
        "query": "education",
        "factual_summary": None,
        "citation_handles": [],
        "missing_points": [],
    }
    chat = FakeChatProvider([repeated_tool_call, repeated_tool_call])
    agent = ProfileAgent(
        chat,
        ProfileAgentTools(retrieval, grant_id=uuid4()),
        max_tool_calls=1,
        output_retries=1,
    )

    run = asyncio.run(agent.run(ProfileAgentInput(question="education", recent_context="")))

    assert run.output.status == AgentResultStatus.BUDGET_EXHAUSTED
    assert run.local_state.tool_call_count == 1
    assert len(retrieval.calls) == 1


def test_structured_step_failure_retries_once_without_leaking_raw_output() -> None:
    chat = FakeChatProvider(
        [
            "not-json",
            {
                "action": "finish",
                "tool_name": None,
                "query": None,
                "factual_summary": "资料不足，无法确认。",
                "citation_handles": [],
                "missing_points": ["Education evidence is missing."],
            },
        ]
    )
    agent = ProfileAgent(
        chat,
        ProfileAgentTools(FakeRetrievalService(), grant_id=uuid4()),
        max_tool_calls=2,
        output_retries=1,
    )

    run = asyncio.run(agent.run(ProfileAgentInput(question="education", recent_context="")))

    assert run.output.status == AgentResultStatus.NOT_FOUND
    assert run.local_state.llm_call_count == 2
    assert "not-json" not in run.output.factual_summary
