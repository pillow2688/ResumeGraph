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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.document_version import DocumentVersion


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="ck_document_chunks_index_nonnegative"),
        CheckConstraint(
            "character_count >= 0",
            name="ck_document_chunks_character_count_nonnegative",
        ),
        UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_document_chunks_version_index",
        ),
        Index("ix_document_chunks_document_version_id", "document_version_id"),
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    document_version: Mapped[DocumentVersion] = relationship(back_populates="chunks")
