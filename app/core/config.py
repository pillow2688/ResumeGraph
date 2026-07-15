from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed environment configuration with secrets masked in object representations."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="RESUMEGRAPH_",
        extra="ignore",
        frozen=True,
    )

    app_name: str = "ResumeGraph API"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://resumegraph:resumegraph-local-only@127.0.0.1:5432/resumegraph"
    )
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    readiness_timeout_seconds: float = Field(default=1.0, gt=0, le=10)
    dependency_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    admin_session_cookie_name: str = Field(
        default="resumegraph_admin_session",
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    admin_session_ttl_seconds: int = Field(default=8 * 60 * 60, gt=0, le=7 * 24 * 60 * 60)
    cookie_secure: bool = False
    admin_login_max_failures: int = Field(default=5, gt=0, le=100)
    admin_login_window_seconds: int = Field(default=5 * 60, gt=0, le=24 * 60 * 60)
    access_token_pepper: SecretStr = Field(
        default=SecretStr("local-development-access-token-pepper-change-me"),
        min_length=32,
    )
    recruiter_session_cookie_name: str = Field(
        default="resumegraph_recruiter_session",
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    recruiter_session_ttl_seconds: int = Field(default=4 * 60 * 60, gt=0, le=7 * 24 * 60 * 60)
    access_exchange_failure_limit: int = Field(default=10, gt=0, le=100)
    access_exchange_failure_window_seconds: int = Field(
        default=10 * 60,
        gt=0,
        le=24 * 60 * 60,
    )
    markdown_max_bytes: int = Field(default=1024 * 1024, gt=0)
    chunk_max_characters: int = Field(default=2_000, gt=0, le=100_000)

    @model_validator(mode="after")
    def validate_security_settings(self) -> Self:
        if self.environment == "production" and not self.cookie_secure:
            raise ValueError("RESUMEGRAPH_COOKIE_SECURE must be true in production.")
        if self.admin_session_cookie_name == self.recruiter_session_cookie_name:
            raise ValueError("Administrator and recruiter cookie names must differ.")
        if (
            self.environment == "production"
            and self.access_token_pepper.get_secret_value()
            == "local-development-access-token-pepper-change-me"
        ):
            raise ValueError("RESUMEGRAPH_ACCESS_TOKEN_PEPPER must be changed in production.")
        return self
