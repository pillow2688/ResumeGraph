from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.access_grant import AccessGrant
    from app.models.project import Project


class GrantProject(Base):
    __tablename__ = "grant_projects"
    __table_args__ = (Index("ix_grant_projects_project_id", "project_id"),)

    grant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("access_grants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )

    grant: Mapped[AccessGrant] = relationship(back_populates="project_links")
    project: Mapped[Project] = relationship(back_populates="grant_links")
