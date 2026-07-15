from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


class DocumentChunkUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool


class EmbeddingConfigResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_name: str
    base_url: AnyHttpUrl
    model: str
    dimensions: int = Field(gt=0)
    send_dimensions: bool
    batch_size: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0)
    max_retries: int = Field(ge=0)


class PublicationState(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: UUID
    current_published_version_id: UUID | None
