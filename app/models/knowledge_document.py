from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.document_version import DocumentVersion
    from app.models.project import Project


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index("ix_knowledge_documents_project_id", "project_id"),
        Index(
            "ix_knowledge_documents_current_published_version_id",
            "current_published_version_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id"))
    title: Mapped[str] = mapped_column(String(200))
    current_published_version_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "document_versions.id",
            name="fk_knowledge_documents_current_published_version_id",
            use_alter=True,
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    project: Mapped[Project] = relationship(back_populates="documents")
    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document",
        foreign_keys="DocumentVersion.document_id",
        passive_deletes=True,
    )
    current_published_version: Mapped[DocumentVersion | None] = relationship(
        foreign_keys=[current_published_version_id],
        post_update=True,
    )
