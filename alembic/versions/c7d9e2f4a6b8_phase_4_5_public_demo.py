"""add phase 4.5 singleton public demo configuration

Revision ID: c7d9e2f4a6b8
Revises: b4f8a1c2d3e5
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7d9e2f4a6b8"
down_revision: str | Sequence[str] | None = "b4f8a1c2d3e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "public_demo_config",
        sa.Column(
            "id",
            sa.SmallInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("candidate_name", sa.String(length=200), nullable=False),
        sa.Column("default_access_grant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_public_demo_config_singleton"),
        sa.ForeignKeyConstraint(
            ["default_access_grant_id"],
            ["access_grants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("public_demo_config")
