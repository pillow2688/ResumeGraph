from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Uuid,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PublicDemoConfig(Base):
    __tablename__ = "public_demo_config"
    __table_args__ = (CheckConstraint("id = 1", name="ck_public_demo_config_singleton"),)

    id: Mapped[int] = mapped_column(
        SmallInteger,
        primary_key=True,
        default=1,
        server_default=text("1"),
    )
    candidate_name: Mapped[str] = mapped_column(String(200))
    default_access_grant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("access_grants.id"),
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
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
