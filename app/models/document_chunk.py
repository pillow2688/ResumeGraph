from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.chunk_embedding import ChunkEmbedding
    from app.models.document_version import DocumentVersion


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="ck_document_chunks_index_nonnegative"),
        CheckConstraint(
            "character_count >= 0",
            name="ck_document_chunks_character_count_nonnegative",
        ),
        CheckConstraint(
            "disabled_reason IS NULL OR disabled_reason IN "
            "('hard_block', 'exact_duplicate', 'quality', 'administrator')",
            name="ck_document_chunks_disabled_reason_valid",
        ),
        CheckConstraint(
            "((enabled IS TRUE AND disabled_reason IS NULL) OR "
            "(enabled IS FALSE AND disabled_reason IS NOT NULL))",
            name="ck_document_chunks_enabled_reason_consistent",
        ),
        UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_document_chunks_version_index",
        ),
        Index("ix_document_chunks_document_version_id", "document_version_id"),
        Index(
            "ix_document_chunks_deduplication",
            "content_hash",
            "enabled",
            "disabled_reason",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("document_versions.id", ondelete="CASCADE"),
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    heading_path: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        server_default=text("'[]'::json"),
    )
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    character_count: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
    )
    disabled_reason: Mapped[str | None] = mapped_column(String(32))
    auto_indexable: Mapped[bool | None] = mapped_column(Boolean)
    quality_issues: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    extracted_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    quality_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality_model: Mapped[str | None] = mapped_column(String(100))
    quality_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    document_version: Mapped[DocumentVersion] = relationship(back_populates="chunks")
    embeddings: Mapped[list[ChunkEmbedding]] = relationship(
        back_populates="chunk",
        passive_deletes=True,
    )
