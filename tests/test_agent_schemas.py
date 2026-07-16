from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agent.schemas import (
    AgentName,
    AgentResultStatus,
    FinalAnswerStatus,
    ProfileAgentOutput,
    ProjectAgentOutput,
    SupervisorDecision,
    TechnicalAgentOutput,
    VerificationAgentOutput,
)
from app.agent.state import InterviewGraphState


def test_supervisor_decision_is_strict_deduplicated_and_agent_whitelisted() -> None:
    project_id = uuid4()
    decision = SupervisorDecision(
        selected_agents=["project_agent", "technical_agent", "project_agent"],
        target_project_ids=[project_id, project_id],
        technical_topics=["Redis", "Redis"],
        needs_comparison=False,
        response_strategy="Combine current implementation with general principles.",
    )

    assert decision.selected_agents == [
        AgentName.PROJECT,
        AgentName.TECHNICAL,
    ]
    assert decision.target_project_ids == [project_id]
    assert decision.technical_topics == ["Redis"]

    with pytest.raises(ValidationError):
        SupervisorDecision(
            selected_agents=["database_agent"],  # type: ignore[list-item]
            target_project_ids=[],
            technical_topics=[],
            needs_comparison=False,
            response_strategy="Invalid agent.",
        )
    with pytest.raises(ValidationError):
        SupervisorDecision(
            selected_agents=["profile_agent"],
            target_project_ids=[],
            technical_topics=[],
            needs_comparison=False,
            response_strategy="Strict output.",
            reasoning="private",  # type: ignore[call-arg]
        )


def test_specialist_outputs_are_distinct_strict_schemas_with_deduplicated_handles() -> None:
    profile = ProfileAgentOutput(
        status="found",
        factual_summary="I studied software engineering.",
        citation_handles=["evidence_1", "evidence_1"],
        evidence=[],
        missing_points=[],
    )
    project = ProjectAgentOutput(
        status="partial",
        factual_summary="Redis currently stores sessions.",
        citation_handles=["evidence_2"],
        evidence=[],
        implemented_evidence=[],
        planned_evidence=[],
        missing_points=["No benchmark metrics."],
    )
    technical = TechnicalAgentOutput(
        status=AgentResultStatus.FOUND,
        factual_summary="Cache avalanche means many keys expire together.",
        citation_handles=["evidence_3"],
        evidence=[],
        missing_points=[],
        project_implementation_requires_project_evidence=True,
    )

    assert profile.citation_handles == ["evidence_1"]
    assert project.status == AgentResultStatus.PARTIAL
    assert technical.project_implementation_requires_project_evidence is True
    assert type(profile) is not type(project) is not type(technical)


def test_verification_output_has_exact_publicly_required_shape_and_bounds() -> None:
    result = VerificationAgentOutput(
        passed=False,
        unsupported_claims=["P99 is not supported."],
        boundary_violations=["General knowledge was stated as implemented."],
        invalid_citation_handles=["evidence_99", "evidence_99"],
        repair_instruction="Remove the metric and state the implementation boundary.",
    )

    assert result.invalid_citation_handles == ["evidence_99"]
    assert set(result.model_dump()) == {
        "passed",
        "unsupported_claims",
        "boundary_violations",
        "invalid_citation_handles",
        "repair_instruction",
    }
    with pytest.raises(ValidationError):
        VerificationAgentOutput(
            passed=True,
            unsupported_claims=[],
            boundary_violations=[],
            invalid_citation_handles=[],
            repair_instruction="",
            final_answer="Agents cannot write the final answer.",  # type: ignore[call-arg]
        )


def test_final_status_enum_rejects_unknown_states() -> None:
    assert FinalAnswerStatus.ANSWERED_WITH_BOUNDARY.value == "answered_with_boundary"
    with pytest.raises(ValueError):
        FinalAnswerStatus("mostly_answered")


def test_graph_state_declares_required_keys_and_excludes_sensitive_or_reasoning_fields() -> None:
    keys = set(InterviewGraphState.__annotations__)
    assert {
        "run_id",
        "conversation_id",
        "recruiter_session_id",
        "grant_id",
        "allowed_project_ids",
        "effective_project_ids",
        "current_question",
        "recent_messages",
        "conversation_summary",
        "active_project_ids",
        "active_technical_topics",
        "selected_agents",
        "agent_results",
        "evidence_registry",
        "draft_answer",
        "verification_result",
        "final_answer",
        "final_status",
        "citations",
        "remaining_requests",
        "tool_call_count",
        "llm_call_count",
        "graph_step_count",
        "repair_count",
        "public_events",
    } <= keys
    assert (
        not {
            "api_key",
            "cookie",
            "access_token",
            "chain_of_thought",
            "reasoning_content",
            "system_prompt",
        }
        & keys
    )
