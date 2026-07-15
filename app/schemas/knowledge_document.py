from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

DocumentTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
DocumentSourceType = Literal["pasted_markdown", "markdown_file"]
DocumentScope = Literal["profile", "project"]
DocumentStatus = Literal[
    "draft",
    "processing",
    "ready_for_review",
    "indexing",
    "indexing_failed",
    "ready_to_publish",
    "published",
    "superseded",
]


class KnowledgeDocumentCreateRequest(BaseModel):
    title: DocumentTitle
    content: str


class KnowledgeDocumentUpdateRequest(BaseModel):
    title: DocumentTitle


class KnowledgeDocumentDeleteRequest(BaseModel):
    confirmation_title: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class DocumentVersionCreateRequest(BaseModel):
    content: str


class DocumentProjectSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    name: str


class DocumentVersionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    document_id: UUID
    version_number: int
    source_type: DocumentSourceType
    original_filename: str | None
    status: DocumentStatus
    created_at: datetime
    content_size_bytes: int


class DocumentVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    document_id: UUID
    version_number: int
    source_type: DocumentSourceType
    original_filename: str | None
    raw_content: str
    status: DocumentStatus
    created_at: datetime
    content_size_bytes: int


class KnowledgeDocumentSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID | None
    document_scope: DocumentScope = "project"
    title: str
    created_at: datetime
    updated_at: datetime
    version_count: int
    latest_version: DocumentVersionSummary | None
    current_published_version_id: UUID | None = None
    current_published_version_number: int | None = None
    current_chunk_count: int = 0
    current_enabled_chunk_count: int = 0
    current_exact_duplicate_count: int = 0
    current_hard_block_count: int = 0
    current_embedding_count: int = 0


class KnowledgeDocumentDetail(KnowledgeDocumentSummary):
    project: DocumentProjectSummary | None
