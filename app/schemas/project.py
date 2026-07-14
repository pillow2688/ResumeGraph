from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator

ProjectName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
ProjectDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=5000),
]


class ProjectCreateRequest(BaseModel):
    name: ProjectName
    description: ProjectDescription = ""


class ProjectUpdateRequest(BaseModel):
    name: ProjectName | None = None
    description: ProjectDescription | None = None

    @field_validator("name", "description", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Project update fields must not be null.")
        return value

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one project field is required.")
        return self


class ProjectResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
