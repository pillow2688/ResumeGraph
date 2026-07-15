"""create minimal phase 2.4 knowledge indexing storage

Revision ID: c8e4f1a7b2d9
Revises: f3a9c2d8e4b1
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c8e4f1a7b2d9"
down_revision: str | Sequence[str] | None = "f3a9c2d8e4b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.drop_constraint(
        "ck_document_versions_status_valid",
        "document_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_document_versions_status_valid",
        "document_versions",
        "status IN ('draft', 'processing', 'ready_for_review', 'indexing', "
        "'indexing_failed', 'ready_to_publish', 'published', 'superseded')",
    )

    op.drop_constraint(
        "ck_ingestion_jobs_stage_valid",
        "ingestion_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ingestion_jobs_stage_valid",
        "ingestion_jobs",
        "stage IN ('reading', 'cleaning', 'chunking', 'saving', 'rule_check', "
        "'llm_quality_check', 'embedding')",
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column(
            "job_type",
            sa.String(length=32),
            server_default=sa.text("'document_processing'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_ingestion_jobs_type_valid",
        "ingestion_jobs",
        "job_type IN ('document_processing', 'knowledge_indexing')",
    )

    op.add_column(
        "document_chunks",
        sa.Column("auto_indexable", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column(
            "quality_issues",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "document_chunks",
        sa.Column(
            "extracted_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "document_chunks",
        sa.Column("quality_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("quality_model", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("quality_reason", sa.Text(), nullable=True),
    )

    op.create_table(
        "chunk_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "dimensions > 0",
            name="ck_chunk_embeddings_dimensions_positive",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chunk_id",
            "provider_name",
            "model_name",
            "dimensions",
            name="uq_chunk_embeddings_chunk_provider_model_dimensions",
        ),
    )
    op.create_index(
        "ix_chunk_embeddings_chunk_id",
        "chunk_embeddings",
        ["chunk_id"],
        unique=False,
    )

    op.add_column(
        "knowledge_documents",
        sa.Column("current_published_version_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_documents_current_published_version_id",
        "knowledge_documents",
        "document_versions",
        ["current_published_version_id"],
        ["id"],
    )
    op.create_index(
        "ix_knowledge_documents_current_published_version_id",
        "knowledge_documents",
        ["current_published_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.execute(
        "UPDATE document_versions SET status = 'ready_for_review' "
        "WHERE status IN ('indexing', 'indexing_failed', 'ready_to_publish', "
        "'published', 'superseded')"
    )
    op.execute("UPDATE knowledge_documents SET current_published_version_id = NULL")
    op.drop_index(
        "ix_knowledge_documents_current_published_version_id",
        table_name="knowledge_documents",
    )
    op.drop_constraint(
        "fk_knowledge_documents_current_published_version_id",
        "knowledge_documents",
        type_="foreignkey",
    )
    op.drop_column("knowledge_documents", "current_published_version_id")

    op.drop_index("ix_chunk_embeddings_chunk_id", table_name="chunk_embeddings")
    op.drop_table("chunk_embeddings")

    op.drop_column("document_chunks", "quality_reason")
    op.drop_column("document_chunks", "quality_model")
    op.drop_column("document_chunks", "quality_checked_at")
    op.drop_column("document_chunks", "extracted_metadata")
    op.drop_column("document_chunks", "quality_issues")
    op.drop_column("document_chunks", "auto_indexable")

    # Phase 2.3 has no representation for knowledge-indexing Job history. Remove
    # those rows explicitly instead of letting them masquerade as document Jobs
    # after job_type is dropped. Any unexpected new stage on a surviving legacy
    # Job is conservatively mapped to the old terminal persistence stage.
    op.execute("DELETE FROM ingestion_jobs WHERE job_type = 'knowledge_indexing'")
    op.execute(
        "UPDATE ingestion_jobs SET stage = 'saving' "
        "WHERE stage IN ('rule_check', 'llm_quality_check', 'embedding')"
    )
    op.drop_constraint("ck_ingestion_jobs_type_valid", "ingestion_jobs", type_="check")
    op.drop_column("ingestion_jobs", "job_type")
    op.drop_constraint(
        "ck_ingestion_jobs_stage_valid",
        "ingestion_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ingestion_jobs_stage_valid",
        "ingestion_jobs",
        "stage IN ('reading', 'cleaning', 'chunking', 'saving')",
    )

    op.drop_constraint(
        "ck_document_versions_status_valid",
        "document_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_document_versions_status_valid",
        "document_versions",
        "status IN ('draft', 'processing', 'ready_for_review')",
    )
    op.execute("DROP EXTENSION IF EXISTS vector")
