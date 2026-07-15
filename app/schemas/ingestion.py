from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

IngestionJobStatus = Literal["pending", "processing", "completed", "failed"]
IngestionJobStage = Literal["reading", "cleaning", "chunking", "saving"]


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
    created_at: datetime
