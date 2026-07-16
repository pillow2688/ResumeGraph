import asyncio
import json
from uuid import uuid4

from app.agent.schemas import AgentEvidence, VerificationAgentInput
from app.agent.tools import VerificationAgentTools
from app.agent.verification_agent import VerificationAgent


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


class FakeRevalidator:
    def __init__(self, valid_handles: set[str] | None = None) -> None:
        self.valid_handles = valid_handles
        self.calls: list[dict[str, object]] = []

    async def revalidate(self, **kwargs: object) -> set[str]:
        self.calls.append(kwargs)
        evidence = kwargs["evidence"]
        assert isinstance(evidence, list)
        if self.valid_handles is None:
            return {item.citation_handle for item in evidence}
        return self.valid_handles


def make_evidence(
    *,
    handle: str = "evidence_1",
    scope: str = "project",
    knowledge_type: str = "project_fact",
    knowledge_status: str = "implemented",
    project_id=None,
) -> AgentEvidence:
    return AgentEvidence(
        citation_handle=handle,
        chunk_id=uuid4(),
        content="Fictional published evidence.",
        content_hash="a" * 64,
        document_scope=scope,
        knowledge_type=knowledge_type,
        knowledge_status=knowledge_status,
        project_id=project_id,
        project_name="ResumeGraph" if project_id is not None else None,
        document_id=uuid4(),
        document_title="Verification test",
        version_number=1,
        heading_path=["Test"],
        distance=0.1,
    )


def test_verification_combines_deterministic_and_semantic_findings() -> None:
    project_id = uuid4()
    project = make_evidence(project_id=project_id)
    technical = make_evidence(
        handle="evidence_2",
        scope="technical",
        knowledge_type="technical_knowledge",
        knowledge_status="general_knowledge",
    )
    chat = FakeChatProvider(
        [
            {
                "passed": False,
                "unsupported_claims": [],
                "boundary_violations": [
                    "TTL randomization is general knowledge, not a proven implementation."
                ],
                "invalid_citation_handles": [],
                "repair_instruction": "State that the mechanism is a future option.",
            }
        ]
    )
    revalidator = FakeRevalidator({"evidence_1"})
    tools = VerificationAgentTools(
        revalidator,
        grant_id=uuid4(),
        allowed_project_ids=[project_id],
        effective_project_ids=[project_id],
    )
    agent = VerificationAgent(chat, tools, output_retries=1)

    run = asyncio.run(
        agent.run(
            VerificationAgentInput(
                question="项目怎么解决缓存雪崩？",
                draft_answer="我已经通过 TTL 随机化解决了缓存雪崩。",
                citation_handles=["evidence_1", "evidence_2", "evidence_99"],
                evidence=[project, technical],
            )
        )
    )

    assert run.output.passed is False
    assert set(run.output.invalid_citation_handles) == {"evidence_2", "evidence_99"}
    assert run.output.boundary_violations
    assert run.local_state.tool_call_count == 4
    assert run.local_state.llm_call_count == 1
    assert revalidator.calls[0]["project_ids"] == [project_id]


def test_deterministic_scope_failure_cannot_be_overridden_by_model_pass() -> None:
    allowed, forbidden = uuid4(), uuid4()
    leaked = make_evidence(project_id=forbidden)
    chat = FakeChatProvider(
        [
            {
                "passed": True,
                "unsupported_claims": [],
                "boundary_violations": [],
                "invalid_citation_handles": [],
                "repair_instruction": "",
            }
        ]
    )
    agent = VerificationAgent(
        chat,
        VerificationAgentTools(
            FakeRevalidator(),
            grant_id=uuid4(),
            allowed_project_ids=[allowed],
            effective_project_ids=[allowed],
        ),
        output_retries=1,
    )

    run = asyncio.run(
        agent.run(
            VerificationAgentInput(
                question="Describe the project.",
                draft_answer="I used a private project.",
                citation_handles=["evidence_1"],
                evidence=[leaked],
            )
        )
    )

    assert run.output.passed is False
    assert run.output.boundary_violations
    assert "scope" in run.output.repair_instruction.lower()


def test_verification_structured_output_retries_once_then_safely_fails() -> None:
    project_id = uuid4()
    agent = VerificationAgent(
        FakeChatProvider(["invalid", "still-invalid"]),
        VerificationAgentTools(
            FakeRevalidator(),
            grant_id=uuid4(),
            allowed_project_ids=[project_id],
            effective_project_ids=[project_id],
        ),
        output_retries=1,
    )

    run = asyncio.run(
        agent.run(
            VerificationAgentInput(
                question="Question",
                draft_answer="Draft",
                citation_handles=[],
                evidence=[],
            )
        )
    )

    assert run.output.passed is False
    assert run.local_state.llm_call_count == 2
    assert "invalid" not in run.output.repair_instruction


def test_verification_rejects_fabricated_qps_and_p99_metrics() -> None:
    project_id = uuid4()
    evidence = make_evidence(project_id=project_id)
    chat = FakeChatProvider(
        [
            {
                "passed": False,
                "unsupported_claims": ["QPS 5000 and P99 80ms are not present in evidence."],
                "boundary_violations": [],
                "invalid_citation_handles": [],
                "repair_instruction": "Remove the fabricated performance numbers.",
            }
        ]
    )
    agent = VerificationAgent(
        chat,
        VerificationAgentTools(
            FakeRevalidator(),
            grant_id=uuid4(),
            allowed_project_ids=[project_id],
            effective_project_ids=[project_id],
        ),
        output_retries=1,
    )

    run = asyncio.run(
        agent.run(
            VerificationAgentInput(
                question="ResumeGraph 的 QPS 和 P99 是多少？",
                draft_answer="我的系统达到 5000 QPS，P99 是 80ms。",
                citation_handles=["evidence_1"],
                evidence=[evidence],
            )
        )
    )

    assert run.output.passed is False
    assert "QPS" in run.output.unsupported_claims[0]
    assert "5000" in chat.calls[0]["user_prompt"]
    assert "P99" in chat.calls[0]["user_prompt"]
