from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.security import normalize_admin_username


class AdminLoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return normalize_admin_username(value)


class AdminPrincipal(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    username: str


class AdminLoginResponse(BaseModel):
    admin: AdminPrincipal
