from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent.schemas import (
    DocumentScope,
    FinalAnswerStatus,
    KnowledgeStatus,
    KnowledgeType,
)


class ConversationAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    question: str = Field(min_length=1, max_length=1_000)
    project_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=50)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Question must not be empty.")
        return normalized

    @field_validator("project_ids")
    @classmethod
    def deduplicate_projects(cls, value: list[UUID] | None) -> list[UUID] | None:
        return list(dict.fromkeys(value)) if value is not None else None


class ConversationCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: UUID
    expires_at: datetime
    remaining_requests: int = Field(ge=0)


class InterviewPublicCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_handle: str = Field(pattern=r"^evidence_[1-9][0-9]*$")
    knowledge_type: KnowledgeType
    document_scope: DocumentScope
    knowledge_status: KnowledgeStatus
    project_id: UUID | None = None
    project_name: str | None = Field(default=None, max_length=200)
    document_title: str = Field(min_length=1, max_length=200)
    version_number: int = Field(gt=0)
    heading_path: list[str] = Field(default_factory=list, max_length=20)
    excerpt: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_boundary_metadata(self) -> Self:
        expected = {
            (DocumentScope.PROFILE, KnowledgeStatus.IMPLEMENTED): KnowledgeType.PROFILE_FACT,
            (DocumentScope.PROJECT, KnowledgeStatus.IMPLEMENTED): KnowledgeType.PROJECT_FACT,
            (DocumentScope.PROJECT, KnowledgeStatus.PLANNED): KnowledgeType.PLANNED_SOLUTION,
            (
                DocumentScope.TECHNICAL,
                KnowledgeStatus.GENERAL_KNOWLEDGE,
            ): KnowledgeType.TECHNICAL_KNOWLEDGE,
        }
        if expected.get((self.document_scope, self.knowledge_status)) is not self.knowledge_type:
            raise ValueError("Citation knowledge boundary metadata is inconsistent.")
        if self.document_scope is DocumentScope.PROJECT:
            if self.project_id is None or not self.project_name:
                raise ValueError("Project citations require authorized project metadata.")
        elif self.project_id is not None or self.project_name is not None:
            raise ValueError("Global citations cannot expose project metadata.")
        return self


class InterviewAgentTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agents_used: list[str] = Field(default_factory=list, max_length=5)
    public_path: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("agents_used")
    @classmethod
    def validate_public_agents(cls, values: list[str]) -> list[str]:
        allowed = {
            "profile_agent",
            "project_agent",
            "technical_agent",
            "verification_agent",
        }
        if any(value not in allowed for value in values):
            raise ValueError("Agent trace contains a private or unknown Agent.")
        return list(dict.fromkeys(values))


class ConversationContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    active_project_ids: list[UUID] = Field(default_factory=list, max_length=50)
    active_technical_topics: list[str] = Field(default_factory=list, max_length=10)
    turn_number: int = Field(ge=0, le=10_000)


class ConversationAskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: UUID
    status: FinalAnswerStatus
    answer: str = Field(min_length=1, max_length=12_000)
    citations: list[InterviewPublicCitation] = Field(default_factory=list, max_length=30)
    agent_trace: InterviewAgentTrace
    context: ConversationContext
    remaining_requests: int = Field(ge=0)


class PublicAgentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: str = Field(min_length=1, max_length=50)
    public_message: str = Field(min_length=1, max_length=200)
    timestamp: datetime
    progress: int = Field(ge=0, le=100)
    response: ConversationAskResponse | None = None
