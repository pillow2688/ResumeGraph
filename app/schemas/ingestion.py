from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

IngestionJobStatus = Literal["pending", "processing", "completed", "failed"]
IngestionJobStage = Literal[
    "reading",
    "cleaning",
    "chunking",
    "saving",
    "rule_check",
    "llm_quality_check",
    "embedding",
]
IngestionJobType = Literal["document_processing", "knowledge_indexing"]


class IngestionJobCreateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: UUID
    status: IngestionJobStatus


class IngestionJobDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: UUID
    document_version_id: UUID
    document_id: UUID
    document_title: str
    version_number: int
    status: IngestionJobStatus
    stage: IngestionJobStage
    progress: int
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    job_type: IngestionJobType = "document_processing"


class DocumentChunkResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    document_version_id: UUID
    chunk_index: int
    heading_path: tuple[str, ...]
    content: str
    content_hash: str
    character_count: int
    enabled: bool
    disabled_reason: (
        Literal[
            "hard_block",
            "exact_duplicate",
            "quality",
            "administrator",
        ]
        | None
    ) = None
    created_at: datetime
    auto_indexable: bool | None = None
    quality_issues: list[dict[str, object]] = Field(default_factory=list)
    extracted_metadata: dict[str, object] = Field(default_factory=dict)
    quality_checked_at: datetime | None = None
    quality_model: str | None = None
    quality_reason: str | None = None
