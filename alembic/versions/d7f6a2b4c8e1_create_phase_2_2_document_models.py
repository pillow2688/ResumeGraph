"""create phase 2.2 document models

Revision ID: d7f6a2b4c8e1
Revises: a5b170c969c4
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7f6a2b4c8e1"
down_revision: str | Sequence[str] | None = "a5b170c969c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_documents_project_id",
        "knowledge_documents",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_type IN ('pasted_markdown', 'markdown_file')",
            name="ck_document_versions_source_type_valid",
        ),
        sa.CheckConstraint(
            "status = 'draft'",
            name="ck_document_versions_status_draft",
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name="ck_document_versions_version_number_positive",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "content_hash",
            name="uq_document_versions_document_content_hash",
        ),
        sa.UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_document_versions_document_version_number",
        ),
    )
    op.create_index(
        "ix_document_versions_document_id",
        "document_versions",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_document_versions_document_id", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index("ix_knowledge_documents_project_id", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
