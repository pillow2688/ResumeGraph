from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.access_grant import AccessGrantMetadata


class PublicDemoStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool
    candidate_name: str | None = None
    message: str | None = None

    @model_validator(mode="after")
    def require_matching_availability_fields(self) -> Self:
        if self.available and (self.candidate_name is None or self.message is not None):
            raise ValueError("Available Public Demo status requires a candidate name.")
        if not self.available and (self.message is None or self.candidate_name is not None):
            raise ValueError("Unavailable Public Demo status requires a message.")
        return self


class PublicDemoSessionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    redirect_url: Literal["/interview"] = "/interview"


class PublicDemoUpdateRequest(BaseModel):
    candidate_name: str = Field(min_length=1, max_length=200)
    default_access_grant_id: UUID
    enabled: bool

    @field_validator("candidate_name")
    @classmethod
    def normalize_candidate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Candidate name must not be empty.")
        return normalized


class PublicDemoAdminResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    configured: bool
    candidate_name: str | None = None
    default_access_grant_id: UUID | None = None
    default_access_grant: AccessGrantMetadata | None = None
    enabled: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
