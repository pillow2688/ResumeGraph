from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

DocumentTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
DocumentSourceType = Literal["pasted_markdown", "markdown_file"]
DocumentStatus = Literal["draft", "processing", "ready_for_review"]


class KnowledgeDocumentCreateRequest(BaseModel):
    title: DocumentTitle
    content: str


class KnowledgeDocumentUpdateRequest(BaseModel):
    title: DocumentTitle


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
    project_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    version_count: int
    latest_version: DocumentVersionSummary | None


class KnowledgeDocumentDetail(KnowledgeDocumentSummary):
    project: DocumentProjectSummary
