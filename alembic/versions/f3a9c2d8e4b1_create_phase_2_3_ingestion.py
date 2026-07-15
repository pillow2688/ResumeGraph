"""create phase 2.3 ingestion jobs and document chunks

Revision ID: f3a9c2d8e4b1
Revises: d7f6a2b4c8e1
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a9c2d8e4b1"
down_revision: str | Sequence[str] | None = "d7f6a2b4c8e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_document_versions_status_draft",
        "document_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_document_versions_status_valid",
        "document_versions",
        "status IN ('draft', 'processing', 'ready_for_review')",
    )
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "stage",
            sa.String(length=20),
            server_default=sa.text("'reading'"),
            nullable=False,
        ),
        sa.Column("progress", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_ingestion_jobs_progress_range",
        ),
        sa.CheckConstraint(
            "stage IN ('reading', 'cleaning', 'chunking', 'saving')",
            name="ck_ingestion_jobs_stage_valid",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_ingestion_jobs_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ingestion_jobs_document_version_id",
        "ingestion_jobs",
        ["document_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_ingestion_jobs_status",
        "ingestion_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_ingestion_jobs_active_version",
        "ingestion_jobs",
        ["document_version_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column(
            "heading_path",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "character_count >= 0",
            name="ck_document_chunks_character_count_nonnegative",
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_document_chunks_index_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_document_chunks_version_index",
        ),
    )
    op.create_index(
        "ix_document_chunks_document_version_id",
        "document_chunks",
        ["document_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_document_version_id", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("uq_ingestion_jobs_active_version", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_status", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_document_version_id", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.execute("UPDATE document_versions SET status = 'draft' WHERE status <> 'draft'")
    op.drop_constraint(
        "ck_document_versions_status_valid",
        "document_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_document_versions_status_draft",
        "document_versions",
        "status = 'draft'",
    )
