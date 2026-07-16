from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.knowledge_document import (
    KnowledgeDocumentCreateRequest,
    KnowledgeDocumentSummary,
)


def test_document_create_request_accepts_only_administrator_selected_statuses() -> None:
    implemented = KnowledgeDocumentCreateRequest(
        title="ResumeGraph architecture",
        content="# Implemented",
        knowledge_status="implemented",
    )
    planned = KnowledgeDocumentCreateRequest(
        title="ResumeGraph roadmap",
        content="# Planned",
        knowledge_status="planned",
    )
    technical = KnowledgeDocumentCreateRequest(
        title="Redis principles",
        content="# General knowledge",
        knowledge_status="general_knowledge",
    )

    assert implemented.knowledge_status == "implemented"
    assert planned.knowledge_status == "planned"
    assert technical.knowledge_status == "general_knowledge"

    with pytest.raises(ValidationError):
        KnowledgeDocumentCreateRequest(
            title="Invalid",
            content="# Invalid",
            knowledge_status="model_inferred",  # type: ignore[arg-type]
        )


def test_document_summary_supports_technical_general_knowledge() -> None:
    summary = KnowledgeDocumentSummary(
        id=uuid4(),
        project_id=None,
        document_scope="technical",
        knowledge_status="general_knowledge",
        title="Redis principles",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        version_count=0,
        latest_version=None,
    )

    assert summary.document_scope == "technical"
    assert summary.knowledge_status == "general_knowledge"
