"""add phase 4 technical knowledge and controlled knowledge status

Revision ID: b4f8a1c2d3e5
Revises: e1b7c9d4a2f6
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4f8a1c2d3e5"
down_revision: str | Sequence[str] | None = "e1b7c9d4a2f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "knowledge_status",
            sa.String(length=24),
            server_default=sa.text("'implemented'"),
            nullable=False,
        ),
    )
    op.execute("UPDATE knowledge_documents SET knowledge_status = 'implemented'")

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
    op.create_check_constraint(
        "ck_knowledge_documents_scope_valid",
        "knowledge_documents",
        "document_scope IN ('profile', 'project', 'technical')",
    )
    op.create_check_constraint(
        "ck_knowledge_documents_scope_project",
        "knowledge_documents",
        "((document_scope = 'project' AND project_id IS NOT NULL) OR "
        "(document_scope IN ('profile', 'technical') AND project_id IS NULL))",
    )
    op.create_check_constraint(
        "ck_knowledge_documents_knowledge_status_valid",
        "knowledge_documents",
        "knowledge_status IN ('implemented', 'planned', 'general_knowledge')",
    )
    op.create_check_constraint(
        "ck_knowledge_documents_scope_knowledge_status",
        "knowledge_documents",
        "((document_scope = 'profile' AND knowledge_status = 'implemented') OR "
        "(document_scope = 'project' AND knowledge_status IN ('implemented', 'planned')) OR "
        "(document_scope = 'technical' AND knowledge_status = 'general_knowledge'))",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM knowledge_documents
                WHERE document_scope = 'technical'
                   OR knowledge_status = 'planned'
            ) THEN
                RAISE EXCEPTION
                    'Phase 4 Technical or planned documents must be explicitly removed '
                    'before downgrading; downgrade will not delete business data.';
            END IF;
        END
        $$;
        """
    )

    op.drop_constraint(
        "ck_knowledge_documents_scope_knowledge_status",
        "knowledge_documents",
        type_="check",
    )
    op.drop_constraint(
        "ck_knowledge_documents_knowledge_status_valid",
        "knowledge_documents",
        type_="check",
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
    op.drop_column("knowledge_documents", "knowledge_status")
