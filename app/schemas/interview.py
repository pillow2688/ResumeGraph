from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InterviewAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2_000)
    project_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Question must not be empty.")
        return normalized

    @field_validator("project_ids")
    @classmethod
    def deduplicate_project_ids(cls, value: list[UUID] | None) -> list[UUID] | None:
        return list(dict.fromkeys(value)) if value is not None else None


class ModelInterviewAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["answered", "insufficient_evidence"]
    answer: str = Field(min_length=1, max_length=1_800)
    citation_handles: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_status_citations(self) -> Self:
        if self.status == "answered" and not self.citation_handles:
            raise ValueError("An answered response requires at least one citation.")
        if self.status == "insufficient_evidence" and self.citation_handles:
            raise ValueError("An insufficient response cannot contain citations.")
        return self


class InterviewCitation(BaseModel):
    model_config = ConfigDict(frozen=True)

    citation_handle: str
    document_scope: Literal["profile", "project"]
    project_id: UUID | None
    project_name: str | None
    document_title: str
    version_number: int = Field(gt=0)
    heading_path: list[str]

    @model_validator(mode="after")
    def validate_scope_metadata(self) -> Self:
        if self.document_scope == "profile" and (
            self.project_id is not None or self.project_name is not None
        ):
            raise ValueError("Profile citations cannot contain project metadata.")
        if self.document_scope == "project" and (self.project_id is None or not self.project_name):
            raise ValueError("Project citations require project metadata.")
        return self


class InterviewAskResponse(BaseModel):
    status: Literal["answered", "insufficient_evidence"]
    answer: str
    citations: list[InterviewCitation]
    remaining_requests: int = Field(ge=0)
