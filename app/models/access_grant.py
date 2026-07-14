from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.grant_project import GrantProject


class AccessGrant(Base):
    __tablename__ = "access_grants"
    __table_args__ = (
        CheckConstraint("max_requests > 0", name="ck_access_grants_max_requests_positive"),
        CheckConstraint(
            "request_count >= 0",
            name="ck_access_grants_request_count_nonnegative",
        ),
        Index("ix_access_grants_token_hash", "token_hash", unique=True),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_requests: Mapped[int] = mapped_column(Integer)
    request_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    project_links: Mapped[list[GrantProject]] = relationship(
        back_populates="grant",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
