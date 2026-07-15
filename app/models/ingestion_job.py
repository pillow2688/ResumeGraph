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
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.document_version import DocumentVersion


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_ingestion_jobs_status_valid",
        ),
        CheckConstraint(
            "stage IN ('reading', 'cleaning', 'chunking', 'saving', 'rule_check', "
            "'llm_quality_check', 'embedding')",
            name="ck_ingestion_jobs_stage_valid",
        ),
        CheckConstraint(
            "job_type IN ('document_processing', 'knowledge_indexing')",
            name="ck_ingestion_jobs_type_valid",
        ),
        CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_ingestion_jobs_progress_range",
        ),
        Index("ix_ingestion_jobs_document_version_id", "document_version_id"),
        Index("ix_ingestion_jobs_status", "status"),
        Index(
            "uq_ingestion_jobs_active_version",
            "document_version_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'processing')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("document_versions.id", ondelete="CASCADE"),
    )
    job_type: Mapped[str] = mapped_column(
        String(32),
        default="document_processing",
        server_default=text("'document_processing'"),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default=text("'pending'"),
    )
    stage: Mapped[str] = mapped_column(
        String(20),
        default="reading",
        server_default=text("'reading'"),
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document_version: Mapped[DocumentVersion] = relationship(back_populates="ingestion_jobs")
