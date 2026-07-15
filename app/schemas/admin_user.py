from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from app.core.security import normalize_admin_username
from app.schemas.admin_auth import AdminPrincipal

AdminPassword = Annotated[str, StringConstraints(min_length=12, max_length=128)]


class AdminUserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: AdminPassword

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = normalize_admin_username(value)
        if not normalized or len(normalized) > 100:
            raise ValueError("Administrator username is invalid.")
        return normalized


AdminUserResponse = AdminPrincipal
