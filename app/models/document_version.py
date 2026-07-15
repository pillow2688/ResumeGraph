from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.document_chunk import DocumentChunk
    from app.models.ingestion_job import IngestionJob
    from app.models.knowledge_document import KnowledgeDocument


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        CheckConstraint(
            "version_number > 0",
            name="ck_document_versions_version_number_positive",
        ),
        CheckConstraint(
            "source_type IN ('pasted_markdown', 'markdown_file')",
            name="ck_document_versions_source_type_valid",
        ),
        CheckConstraint(
            "status IN ('draft', 'processing', 'ready_for_review')",
            name="ck_document_versions_status_valid",
        ),
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_document_versions_document_version_number",
        ),
        UniqueConstraint(
            "document_id",
            "content_hash",
            name="uq_document_versions_document_content_hash",
        ),
        Index("ix_document_versions_document_id", "document_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("knowledge_documents.id"))
    version_number: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(32))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    raw_content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(20),
        default="draft",
        server_default=text("'draft'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    document: Mapped[KnowledgeDocument] = relationship(back_populates="versions")
    ingestion_jobs: Mapped[list[IngestionJob]] = relationship(
        back_populates="document_version",
        passive_deletes=True,
    )
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document_version",
        passive_deletes=True,
    )
