from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.agent.tools import ProfileToolName, ProjectToolName, TechnicalToolName

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)]
SummaryText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000),
]
CitationHandle = Annotated[str, StringConstraints(pattern=r"^evidence_[1-9][0-9]*$")]
UntrustedHandle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]


class StrictAgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentName(StrEnum):
    SUPERVISOR = "interview_supervisor"
    PROFILE = "profile_agent"
    PROJECT = "project_agent"
    TECHNICAL = "technical_agent"
    VERIFICATION = "verification_agent"


class AgentResultStatus(StrEnum):
    FOUND = "found"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ERROR = "error"


class FinalAnswerStatus(StrEnum):
    ANSWERED = "answered"
    ANSWERED_WITH_BOUNDARY = "answered_with_boundary"
    PARTIAL_ANSWER = "partial_answer"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    ACCESS_RESTRICTED = "access_restricted"


class KnowledgeType(StrEnum):
    PROFILE_FACT = "profile_fact"
    PROJECT_FACT = "project_fact"
    TECHNICAL_KNOWLEDGE = "technical_knowledge"
    PLANNED_SOLUTION = "planned_solution"


class KnowledgeStatus(StrEnum):
    IMPLEMENTED = "implemented"
    PLANNED = "planned"
    GENERAL_KNOWLEDGE = "general_knowledge"


class DocumentScope(StrEnum):
    PROFILE = "profile"
    PROJECT = "project"
    TECHNICAL = "technical"


class AgentEvidence(StrictAgentModel):
    citation_handle: CitationHandle
    chunk_id: UUID
    content: Annotated[str, StringConstraints(min_length=1, max_length=20_000)]
    content_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    document_scope: DocumentScope
    knowledge_type: KnowledgeType
    knowledge_status: KnowledgeStatus
    project_id: UUID | None = None
    project_name: Annotated[str, StringConstraints(max_length=200)] | None = None
    document_id: UUID
    document_title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    version_number: int = Field(gt=0)
    heading_path: list[Annotated[str, StringConstraints(max_length=200)]] = Field(
        default_factory=list,
        max_length=20,
    )
    distance: float = Field(ge=0)


class SupervisorDecision(StrictAgentModel):
    selected_agents: list[AgentName] = Field(default_factory=list, max_length=3)
    target_project_ids: list[UUID] = Field(default_factory=list, max_length=50)
    technical_topics: list[ShortText] = Field(default_factory=list, max_length=10)
    needs_comparison: bool
    response_strategy: ShortText

    @field_validator("selected_agents")
    @classmethod
    def validate_specialists(cls, values: list[AgentName]) -> list[AgentName]:
        allowed = {AgentName.PROFILE, AgentName.PROJECT, AgentName.TECHNICAL}
        if any(value not in allowed for value in values):
            raise ValueError("Supervisor may select only specialist agents.")
        return list(dict.fromkeys(values))

    @field_validator("target_project_ids", "technical_topics")
    @classmethod
    def deduplicate_sequence[T](cls, values: list[T]) -> list[T]:
        return list(dict.fromkeys(values))


class SpecialistAgentOutput(StrictAgentModel):
    status: AgentResultStatus
    factual_summary: SummaryText
    citation_handles: list[CitationHandle] = Field(default_factory=list, max_length=20)
    evidence: list[AgentEvidence] = Field(default_factory=list, max_length=20)
    missing_points: list[ShortText] = Field(default_factory=list, max_length=20)

    @field_validator("citation_handles")
    @classmethod
    def deduplicate_handles(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


class ProfileAgentOutput(SpecialistAgentOutput):
    pass


class ProjectAgentOutput(SpecialistAgentOutput):
    implemented_evidence: list[AgentEvidence] = Field(default_factory=list, max_length=20)
    planned_evidence: list[AgentEvidence] = Field(default_factory=list, max_length=20)


class TechnicalAgentOutput(SpecialistAgentOutput):
    project_implementation_requires_project_evidence: bool = True


class VerificationAgentOutput(StrictAgentModel):
    passed: bool
    unsupported_claims: list[ShortText] = Field(default_factory=list, max_length=20)
    boundary_violations: list[ShortText] = Field(default_factory=list, max_length=20)
    invalid_citation_handles: list[UntrustedHandle] = Field(default_factory=list, max_length=20)
    repair_instruction: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2_000)]

    @field_validator(
        "unsupported_claims",
        "boundary_violations",
        "invalid_citation_handles",
    )
    @classmethod
    def deduplicate_findings[T](cls, values: list[T]) -> list[T]:
        return list(dict.fromkeys(values))


QuestionText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
]
RecentContextText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=4_000),
]


class ProfileAgentInput(StrictAgentModel):
    question: QuestionText
    recent_context: RecentContextText = ""


class ProjectAgentInput(StrictAgentModel):
    question: QuestionText
    recent_context: RecentContextText = ""
    effective_project_ids: list[UUID] = Field(min_length=1, max_length=50)
    needs_comparison: bool = False

    @field_validator("effective_project_ids")
    @classmethod
    def deduplicate_projects(cls, values: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(values))


class TechnicalAgentInput(StrictAgentModel):
    question: QuestionText
    recent_context: RecentContextText = ""
    technical_topics: list[ShortText] = Field(default_factory=list, max_length=10)

    @field_validator("technical_topics")
    @classmethod
    def deduplicate_topics(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


class AgentAction(StrEnum):
    TOOL_CALL = "tool_call"
    FINISH = "finish"


class SpecialistStepBase(StrictAgentModel):
    action: AgentAction
    query: QuestionText | None = None
    factual_summary: SummaryText | None = None
    citation_handles: list[CitationHandle] = Field(default_factory=list, max_length=20)
    missing_points: list[ShortText] = Field(default_factory=list, max_length=20)

    @field_validator("citation_handles")
    @classmethod
    def deduplicate_step_handles(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_action_payload(self) -> SpecialistStepBase:
        if self.action is AgentAction.FINISH and self.factual_summary is None:
            raise ValueError("A finish action requires factual_summary.")
        return self


class ProfileAgentStep(SpecialistStepBase):
    tool_name: ProfileToolName | None = None

    @model_validator(mode="after")
    def validate_profile_tool(self) -> ProfileAgentStep:
        if self.action is AgentAction.TOOL_CALL and self.tool_name is None:
            raise ValueError("A tool call requires a Profile tool.")
        return self


class ProjectAgentStep(SpecialistStepBase):
    tool_name: ProjectToolName | None = None
    project_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @field_validator("project_ids")
    @classmethod
    def deduplicate_step_projects(cls, values: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_project_tool(self) -> ProjectAgentStep:
        if self.action is AgentAction.TOOL_CALL and self.tool_name is None:
            raise ValueError("A tool call requires a Project tool.")
        return self


class TechnicalAgentStep(SpecialistStepBase):
    tool_name: TechnicalToolName | None = None

    @model_validator(mode="after")
    def validate_technical_tool(self) -> TechnicalAgentStep:
        if self.action is AgentAction.TOOL_CALL and self.tool_name is None:
            raise ValueError("A tool call requires a Technical tool.")
        return self


class SpecialistLocalState(StrictAgentModel):
    tool_call_count: int = Field(default=0, ge=0)
    llm_call_count: int = Field(default=0, ge=0)
    tool_history: list[str] = Field(default_factory=list, max_length=10)
    evidence_registry: dict[str, AgentEvidence] = Field(default_factory=dict)
    tool_results: list[dict[str, object]] = Field(default_factory=list, max_length=10)


class ProfileAgentLocalState(SpecialistLocalState):
    pass


class ProjectAgentLocalState(SpecialistLocalState):
    query_rewrite_count: int = Field(default=0, ge=0, le=1)


class TechnicalAgentLocalState(SpecialistLocalState):
    pass


class VerificationAgentInput(StrictAgentModel):
    question: QuestionText
    draft_answer: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=12_000),
    ]
    citation_handles: list[UntrustedHandle] = Field(default_factory=list, max_length=30)
    evidence: list[AgentEvidence] = Field(default_factory=list, max_length=30)

    @field_validator("citation_handles")
    @classmethod
    def deduplicate_input_handles(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


class VerificationAgentLocalState(StrictAgentModel):
    tool_call_count: int = Field(default=0, ge=0, le=4)
    llm_call_count: int = Field(default=0, ge=0, le=2)
    valid_citation_handles: list[str] = Field(default_factory=list, max_length=30)
    invalid_citation_handles: list[str] = Field(default_factory=list, max_length=30)
    deterministic_violations: list[str] = Field(default_factory=list, max_length=30)


class RecentMessageInput(StrictAgentModel):
    role: Literal["user", "assistant"]
    summary: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1_000)]


class SupervisorAgentInput(StrictAgentModel):
    question: QuestionText
    recent_messages: list[RecentMessageInput] = Field(default_factory=list, max_length=16)
    conversation_summary: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=4_000),
    ] = ""
    allowed_project_ids: list[UUID] = Field(min_length=1, max_length=50)
    effective_project_ids: list[UUID] = Field(min_length=1, max_length=50)
    active_project_ids: list[UUID] = Field(default_factory=list, max_length=50)
    active_technical_topics: list[ShortText] = Field(default_factory=list, max_length=10)

    @field_validator(
        "allowed_project_ids",
        "effective_project_ids",
        "active_project_ids",
        "active_technical_topics",
    )
    @classmethod
    def deduplicate_supervisor_context[T](cls, values: list[T]) -> list[T]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_effective_scope(self) -> SupervisorAgentInput:
        if not set(self.effective_project_ids) <= set(self.allowed_project_ids):
            raise ValueError("Effective project scope must be inside the allowed scope.")
        return self


class SupervisorDraftOutput(StrictAgentModel):
    status: FinalAnswerStatus
    answer: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=12_000),
    ]
    citation_handles: list[CitationHandle] = Field(default_factory=list, max_length=30)

    @field_validator("citation_handles")
    @classmethod
    def deduplicate_draft_handles(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


class SupervisorAgentLocalState(StrictAgentModel):
    specialist_call_count: int = Field(default=0, ge=0, le=4)
    llm_call_count: int = Field(default=0, ge=0)
    selected_agents: list[AgentName] = Field(default_factory=list, max_length=3)
