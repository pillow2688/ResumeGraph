from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProjectSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    name: str


class AccessGrantCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    expires_at: datetime
    max_requests: int = Field(gt=0, le=1_000_000)
    project_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Grant name must not be empty.")
        return normalized

    @field_validator("project_ids")
    @classmethod
    def deduplicate_projects(cls, value: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def require_timezone_aware_expiry(self) -> Self:
        if self.expires_at.utcoffset() is None:
            raise ValueError("Grant expiry must include a timezone.")
        return self


class AccessGrantMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    name: str
    expires_at: datetime
    max_requests: int
    request_count: int
    revoked_at: datetime | None
    created_at: datetime
    projects: list[ProjectSummary]


class AccessGrantCreateResponse(BaseModel):
    grant: AccessGrantMetadata
    access_token: str = Field(
        description=(
            "Shown only once. If lost, this token cannot be recovered; revoke the grant "
            "and create a replacement."
        )
    )


class AccessTokenExchangeRequest(BaseModel):
    access_token: str


class RecruiterPrincipal(BaseModel):
    model_config = ConfigDict(frozen=True)

    grant_id: UUID
    grant_name: str
    allowed_project_ids: list[UUID]
    grant_expires_at: datetime
    remaining_requests: int
    allowed_projects: list[ProjectSummary]


class RecruiterAccessResponse(BaseModel):
    grant_id: UUID
    grant_name: str
    expires_at: datetime
    remaining_requests: int
    allowed_projects: list[ProjectSummary]

    @classmethod
    def from_principal(cls, principal: RecruiterPrincipal) -> Self:
        return cls(
            grant_id=principal.grant_id,
            grant_name=principal.grant_name,
            expires_at=principal.grant_expires_at,
            remaining_requests=principal.remaining_requests,
            allowed_projects=principal.allowed_projects,
        )


class RecruiterExchangeResponse(BaseModel):
    recruiter: RecruiterAccessResponse
