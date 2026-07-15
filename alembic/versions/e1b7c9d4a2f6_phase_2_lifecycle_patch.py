"""complete the phase 2 knowledge lifecycle

Revision ID: e1b7c9d4a2f6
Revises: c8e4f1a7b2d9
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1b7c9d4a2f6"
down_revision: str | Sequence[str] | None = "c8e4f1a7b2d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "document_scope",
            sa.String(length=20),
            server_default=sa.text("'project'"),
            nullable=False,
        ),
    )
    op.execute("UPDATE knowledge_documents SET document_scope = 'project'")
    op.alter_column(
        "knowledge_documents",
        "project_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
    op.create_check_constraint(
        "ck_knowledge_documents_scope_valid",
        "knowledge_documents",
        "document_scope IN ('profile', 'project')",
    )
    op.create_check_constraint(
        "ck_knowledge_documents_scope_project",
        "knowledge_documents",
        "((document_scope = 'project' AND project_id IS NOT NULL) OR "
        "(document_scope = 'profile' AND project_id IS NULL))",
    )
    op.create_index(
        "ix_knowledge_documents_scope_published",
        "knowledge_documents",
        ["document_scope", "current_published_version_id"],
        unique=False,
    )

    op.add_column(
        "document_chunks",
        sa.Column("disabled_reason", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE document_chunks
        SET disabled_reason = CASE
            WHEN EXISTS (
                SELECT 1
                FROM jsonb_array_elements(quality_issues) AS issue
                WHERE issue->>'severity' = 'hard_block'
                  AND issue->>'code' <> 'exact_duplicate'
            ) THEN 'hard_block'
            WHEN quality_issues @> '[{"code":"exact_duplicate"}]'::jsonb
                THEN 'exact_duplicate'
            WHEN auto_indexable IS FALSE THEN 'quality'
            ELSE 'administrator'
        END
        WHERE enabled IS FALSE
        """
    )
    op.create_check_constraint(
        "ck_document_chunks_disabled_reason_valid",
        "document_chunks",
        "disabled_reason IS NULL OR disabled_reason IN "
        "('hard_block', 'exact_duplicate', 'quality', 'administrator')",
    )
    op.create_check_constraint(
        "ck_document_chunks_enabled_reason_consistent",
        "document_chunks",
        "((enabled IS TRUE AND disabled_reason IS NULL) OR "
        "(enabled IS FALSE AND disabled_reason IS NOT NULL))",
    )
    op.create_index(
        "ix_document_chunks_deduplication",
        "document_chunks",
        ["content_hash", "enabled", "disabled_reason"],
        unique=False,
    )

    op.drop_constraint(
        "document_versions_document_id_fkey",
        "document_versions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_document_versions_document_id_knowledge_documents",
        "document_versions",
        "knowledge_documents",
        ["document_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE knowledge_documents SET current_published_version_id = NULL "
        "WHERE document_scope = 'profile'"
    )
    op.execute("DELETE FROM knowledge_documents WHERE document_scope = 'profile'")

    op.drop_constraint(
        "fk_document_versions_document_id_knowledge_documents",
        "document_versions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "document_versions_document_id_fkey",
        "document_versions",
        "knowledge_documents",
        ["document_id"],
        ["id"],
    )

    op.drop_index("ix_document_chunks_deduplication", table_name="document_chunks")
    op.drop_constraint(
        "ck_document_chunks_enabled_reason_consistent",
        "document_chunks",
        type_="check",
    )
    op.drop_constraint(
        "ck_document_chunks_disabled_reason_valid",
        "document_chunks",
        type_="check",
    )
    op.drop_column("document_chunks", "disabled_reason")

    op.drop_index(
        "ix_knowledge_documents_scope_published",
        table_name="knowledge_documents",
    )
    op.drop_constraint(
        "ck_knowledge_documents_scope_project",
        "knowledge_documents",
        type_="check",
    )
    op.drop_constraint(
        "ck_knowledge_documents_scope_valid",
        "knowledge_documents",
        type_="check",
    )
    op.alter_column(
        "knowledge_documents",
        "project_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.drop_column("knowledge_documents", "document_scope")
