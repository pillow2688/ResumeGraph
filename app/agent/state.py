from __future__ import annotations

from typing import TypedDict
from uuid import UUID

from app.agent.schemas import (
    AgentEvidence,
    AgentName,
    FinalAnswerStatus,
    SpecialistAgentOutput,
    SupervisorAgentLocalState,
    SupervisorDecision,
    SupervisorDraftOutput,
    VerificationAgentOutput,
)


class RecentMessage(TypedDict):
    role: str
    summary: str


class PublicEventState(TypedDict):
    event_type: str
    public_message: str
    timestamp: str
    progress: int


class InterviewGraphState(TypedDict):
    run_id: UUID
    conversation_id: UUID
    recruiter_session_id: str
    grant_id: UUID
    allowed_project_ids: list[UUID]
    effective_project_ids: list[UUID]
    current_question: str
    recent_messages: list[RecentMessage]
    conversation_summary: str
    active_project_ids: list[UUID]
    active_technical_topics: list[str]
    selected_agents: list[AgentName]
    supervisor_decision: SupervisorDecision | None
    supervisor_draft: SupervisorDraftOutput | None
    supervisor_local_state: SupervisorAgentLocalState
    agent_results: dict[str, SpecialistAgentOutput]
    evidence_registry: dict[str, AgentEvidence]
    draft_answer: str
    verification_result: VerificationAgentOutput | None
    final_answer: str
    final_status: FinalAnswerStatus
    citations: list[str]
    remaining_requests: int
    tool_call_count: int
    llm_call_count: int
    graph_step_count: int
    repair_count: int
    verification_run_count: int
    agents_used: list[str]
    public_path: list[str]
    budget_exhausted: bool
    public_events: list[PublicEventState]
