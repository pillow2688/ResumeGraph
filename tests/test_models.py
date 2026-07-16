from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import configure_mappers

from app import models


def test_phase_2_4_metadata_contains_only_the_requested_tables() -> None:
    assert set(models.Base.metadata.tables) == {
        "access_grants",
        "admin_users",
        "chunk_embeddings",
        "document_chunks",
        "document_versions",
        "grant_projects",
        "ingestion_jobs",
        "knowledge_documents",
        "projects",
        "public_demo_config",
    }


@pytest.mark.parametrize(
    ("model_name", "expected_columns"),
    [
        (
            "AdminUser",
            {"id", "username", "password_hash", "created_at", "updated_at"},
        ),
        (
            "Project",
            {"id", "name", "description", "created_at", "updated_at"},
        ),
        (
            "AccessGrant",
            {
                "id",
                "name",
                "token_hash",
                "expires_at",
                "max_requests",
                "request_count",
                "revoked_at",
                "created_at",
            },
        ),
        (
            "PublicDemoConfig",
            {
                "id",
                "candidate_name",
                "default_access_grant_id",
                "enabled",
                "created_at",
                "updated_at",
            },
        ),
        ("GrantProject", {"grant_id", "project_id"}),
        (
            "KnowledgeDocument",
            {
                "id",
                "project_id",
                "document_scope",
                "knowledge_status",
                "title",
                "current_published_version_id",
                "created_at",
                "updated_at",
            },
        ),
        (
            "DocumentVersion",
            {
                "id",
                "document_id",
                "version_number",
                "source_type",
                "original_filename",
                "raw_content",
                "content_hash",
                "status",
                "created_at",
            },
        ),
        (
            "IngestionJob",
            {
                "id",
                "document_version_id",
                "status",
                "stage",
                "job_type",
                "progress",
                "error_message",
                "created_at",
                "started_at",
                "finished_at",
            },
        ),
        (
            "DocumentChunk",
            {
                "id",
                "document_version_id",
                "chunk_index",
                "heading_path",
                "content",
                "content_hash",
                "character_count",
                "enabled",
                "disabled_reason",
                "auto_indexable",
                "quality_issues",
                "extracted_metadata",
                "quality_checked_at",
                "quality_model",
                "quality_reason",
                "created_at",
            },
        ),
        (
            "ChunkEmbedding",
            {
                "id",
                "chunk_id",
                "embedding",
                "provider_name",
                "model_name",
                "dimensions",
                "content_hash",
                "created_at",
            },
        ),
    ],
)
def test_models_expose_exactly_the_requested_columns(
    model_name: str,
    expected_columns: set[str],
) -> None:
    table = getattr(models, model_name).__table__

    assert set(table.columns.keys()) == expected_columns
    assert "token" not in table.columns
    assert "revoked" not in table.columns


def test_column_types_nullability_defaults_and_indexes() -> None:
    admin_users = models.AdminUser.__table__
    projects = models.Project.__table__
    access_grants = models.AccessGrant.__table__

    assert isinstance(admin_users.c.id.type, Uuid)
    assert isinstance(admin_users.c.username.type, String)
    assert admin_users.c.username.type.length == 100
    assert admin_users.c.username.nullable is False
    assert admin_users.c.username.unique is True
    assert isinstance(admin_users.c.password_hash.type, String)
    assert admin_users.c.password_hash.type.length == 255

    assert isinstance(projects.c.name.type, String)
    assert projects.c.name.type.length == 200
    assert isinstance(projects.c.description.type, Text)
    assert projects.c.description.nullable is False
    assert projects.c.description.server_default is not None

    assert isinstance(access_grants.c.token_hash.type, String)
    assert access_grants.c.token_hash.type.length == 255
    assert access_grants.c.token_hash.nullable is False
    assert any(
        index.unique and tuple(column.name for column in index.columns) == ("token_hash",)
        for index in access_grants.indexes
    )
    assert isinstance(access_grants.c.expires_at.type, DateTime)
    assert access_grants.c.expires_at.type.timezone is True
    assert isinstance(access_grants.c.max_requests.type, Integer)
    assert isinstance(access_grants.c.request_count.type, Integer)
    assert access_grants.c.request_count.server_default is not None
    assert isinstance(access_grants.c.revoked_at.type, DateTime)
    assert access_grants.c.revoked_at.type.timezone is True
    assert access_grants.c.revoked_at.nullable is True
    assert not any(isinstance(column.type, Boolean) for column in access_grants.columns)

    check_constraints = {
        str(constraint.sqltext)
        for constraint in access_grants.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert check_constraints == {"max_requests > 0", "request_count >= 0"}


def test_timestamps_use_database_defaults_and_only_orm_updated_at_uses_onupdate() -> None:
    for model in (models.AdminUser, models.Project):
        created_at = model.__table__.c.created_at
        updated_at = model.__table__.c.updated_at

        assert created_at.server_default is not None
        assert created_at.onupdate is None
        assert updated_at.server_default is not None
        assert updated_at.onupdate is not None
        assert isinstance(created_at.type, DateTime)
        assert created_at.type.timezone is True
        assert isinstance(updated_at.type, DateTime)
        assert updated_at.type.timezone is True

    assert models.AccessGrant.__table__.c.created_at.server_default is not None
    assert "updated_at" not in models.AccessGrant.__table__.columns


def test_grants_and_projects_have_many_to_many_relationships_with_passive_deletes() -> None:
    configure_mappers()

    expires_at = datetime.now(UTC) + timedelta(days=7)
    grant = models.AccessGrant(
        name="Fictional recruiter grant",
        token_hash="digest-only",
        expires_at=expires_at,
        max_requests=20,
    )
    project = models.Project(name="Fictional project", description="Published summary")

    link = models.GrantProject(grant=grant, project=project)

    assert grant.project_links == [link]
    assert project.grant_links == [link]
    assert link.grant is grant
    assert link.project is project
    assert models.AccessGrant.project_links.property.passive_deletes is True
    assert models.Project.grant_links.property.passive_deletes is True
    assert "delete-orphan" in models.AccessGrant.project_links.property.cascade
    assert "delete-orphan" in models.Project.grant_links.property.cascade

    association_table = models.Base.metadata.tables["grant_projects"]
    assert tuple(association_table.primary_key.columns.keys()) == ("grant_id", "project_id")
    assert {foreign_key.ondelete for foreign_key in association_table.foreign_keys} == {"CASCADE"}
    assert any(
        tuple(column.name for column in index.columns) == ("project_id",)
        for index in association_table.indexes
    )


def test_knowledge_document_and_version_column_contracts() -> None:
    documents = models.KnowledgeDocument.__table__
    versions = models.DocumentVersion.__table__

    assert isinstance(documents.c.id.type, Uuid)
    assert isinstance(documents.c.project_id.type, Uuid)
    assert documents.c.project_id.nullable is True
    assert isinstance(documents.c.document_scope.type, String)
    assert documents.c.document_scope.type.length == 20
    assert documents.c.document_scope.nullable is False
    assert documents.c.document_scope.server_default is not None
    assert isinstance(documents.c.knowledge_status.type, String)
    assert documents.c.knowledge_status.type.length == 24
    assert documents.c.knowledge_status.nullable is False
    assert documents.c.knowledge_status.server_default is not None
    assert isinstance(documents.c.title.type, String)
    assert documents.c.title.type.length == 200
    assert documents.c.title.nullable is False
    assert isinstance(documents.c.created_at.type, DateTime)
    assert documents.c.created_at.type.timezone is True
    assert documents.c.created_at.server_default is not None
    assert isinstance(documents.c.updated_at.type, DateTime)
    assert documents.c.updated_at.type.timezone is True
    assert documents.c.updated_at.server_default is not None
    assert documents.c.updated_at.onupdate is not None
    assert any(
        tuple(column.name for column in index.columns) == ("project_id",)
        for index in documents.indexes
    )
    assert any(
        tuple(column.name for column in index.columns)
        == ("document_scope", "current_published_version_id")
        for index in documents.indexes
    )
    document_checks = {
        str(constraint.sqltext)
        for constraint in documents.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert document_checks == {
        "document_scope IN ('profile', 'project', 'technical')",
        "knowledge_status IN ('implemented', 'planned', 'general_knowledge')",
        "((document_scope = 'project' AND project_id IS NOT NULL) OR "
        "(document_scope IN ('profile', 'technical') AND project_id IS NULL))",
        "((document_scope = 'profile' AND knowledge_status = 'implemented') OR "
        "(document_scope = 'project' AND knowledge_status IN ('implemented', 'planned')) OR "
        "(document_scope = 'technical' AND knowledge_status = 'general_knowledge'))",
    }

    assert isinstance(versions.c.id.type, Uuid)
    assert isinstance(versions.c.document_id.type, Uuid)
    assert versions.c.document_id.nullable is False
    assert isinstance(versions.c.version_number.type, Integer)
    assert versions.c.version_number.nullable is False
    assert isinstance(versions.c.source_type.type, String)
    assert versions.c.source_type.type.length == 32
    assert isinstance(versions.c.original_filename.type, String)
    assert versions.c.original_filename.type.length == 255
    assert versions.c.original_filename.nullable is True
    assert isinstance(versions.c.raw_content.type, Text)
    assert versions.c.raw_content.nullable is False
    assert isinstance(versions.c.content_hash.type, String)
    assert versions.c.content_hash.type.length == 64
    assert isinstance(versions.c.status.type, String)
    assert versions.c.status.type.length == 20
    assert isinstance(versions.c.created_at.type, DateTime)
    assert versions.c.created_at.type.timezone is True
    assert versions.c.created_at.server_default is not None
    assert any(
        tuple(column.name for column in index.columns) == ("document_id",)
        for index in versions.indexes
    )


def test_document_foreign_keys_constraints_and_relationships_support_document_cascade_only() -> (
    None
):
    configure_mappers()

    documents = models.KnowledgeDocument.__table__
    versions = models.DocumentVersion.__table__

    document_foreign_key = next(iter(documents.c.project_id.foreign_keys))
    version_foreign_key = next(iter(versions.c.document_id.foreign_keys))
    assert document_foreign_key.target_fullname == "projects.id"
    assert document_foreign_key.ondelete is None
    assert version_foreign_key.target_fullname == "knowledge_documents.id"
    assert version_foreign_key.ondelete == "CASCADE"

    unique_constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in versions.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert unique_constraints == {
        ("document_id", "version_number"),
        ("document_id", "content_hash"),
    }
    check_constraints = {
        str(constraint.sqltext)
        for constraint in versions.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert check_constraints == {
        "version_number > 0",
        "source_type IN ('pasted_markdown', 'markdown_file')",
        (
            "status IN ('draft', 'processing', 'ready_for_review', 'indexing', "
            "'indexing_failed', 'ready_to_publish', 'published', 'superseded')"
        ),
    }

    project = models.Project(name="Fictional knowledge project", description="")
    document = models.KnowledgeDocument(
        project=project,
        document_scope="project",
        title="Design notes",
    )
    version = models.DocumentVersion(
        document=document,
        version_number=1,
        source_type="pasted_markdown",
        original_filename=None,
        raw_content="# Design",
        content_hash="a" * 64,
        status="draft",
    )

    assert project.documents == [document]
    assert document.project is project
    assert document.versions == [version]
    assert version.document is document
    assert "delete" not in models.Project.documents.property.cascade
    assert "delete-orphan" not in models.Project.documents.property.cascade
    assert models.Project.documents.property.passive_deletes is True
    assert models.KnowledgeDocument.versions.property.passive_deletes is True

    profile_document = models.KnowledgeDocument(
        project_id=None,
        document_scope="profile",
        knowledge_status="implemented",
        title="AI Agent resume",
    )
    assert profile_document.project_id is None
    assert profile_document.document_scope == "profile"

    technical_document = models.KnowledgeDocument(
        project_id=None,
        document_scope="technical",
        knowledge_status="general_knowledge",
        title="Redis principles",
    )
    assert technical_document.project_id is None
    assert technical_document.document_scope == "technical"
    assert technical_document.knowledge_status == "general_knowledge"


def test_phase_2_4_indexing_models_have_exact_constraints_and_relationships() -> None:
    configure_mappers()

    versions = models.DocumentVersion.__table__
    jobs = models.IngestionJob.__table__
    chunks = models.DocumentChunk.__table__

    version_checks = {
        str(constraint.sqltext)
        for constraint in versions.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert any("ready_to_publish" in check for check in version_checks)
    assert "status = 'draft'" not in version_checks

    job_checks = {
        str(constraint.sqltext)
        for constraint in jobs.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert job_checks == {
        "status IN ('pending', 'processing', 'completed', 'failed')",
        (
            "stage IN ('reading', 'cleaning', 'chunking', 'saving', 'rule_check', "
            "'llm_quality_check', 'embedding')"
        ),
        "job_type IN ('document_processing', 'knowledge_indexing')",
        "progress >= 0 AND progress <= 100",
    }
    assert isinstance(jobs.c.error_message.type, Text)
    assert jobs.c.error_message.nullable is True
    assert jobs.c.started_at.nullable is True
    assert jobs.c.finished_at.nullable is True
    assert any(
        index.unique
        and tuple(column.name for column in index.columns) == ("document_version_id",)
        and index.dialect_options["postgresql"].get("where") is not None
        for index in jobs.indexes
    )

    assert isinstance(chunks.c.heading_path.type, JSON)
    assert isinstance(chunks.c.content.type, Text)
    assert isinstance(chunks.c.enabled.type, Boolean)
    assert chunks.c.enabled.server_default is not None
    assert isinstance(chunks.c.disabled_reason.type, String)
    assert chunks.c.disabled_reason.type.length == 32
    assert chunks.c.disabled_reason.nullable is True
    chunk_checks = {
        str(constraint.sqltext)
        for constraint in chunks.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert chunk_checks == {
        "chunk_index >= 0",
        "character_count >= 0",
        "disabled_reason IS NULL OR disabled_reason IN "
        "('hard_block', 'exact_duplicate', 'quality', 'administrator')",
        "((enabled IS TRUE AND disabled_reason IS NULL) OR "
        "(enabled IS FALSE AND disabled_reason IS NOT NULL))",
    }
    assert any(
        tuple(column.name for column in index.columns)
        == ("content_hash", "enabled", "disabled_reason")
        for index in chunks.indexes
    )
    chunk_uniques = {
        tuple(column.name for column in constraint.columns)
        for constraint in chunks.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert chunk_uniques == {("document_version_id", "chunk_index")}
    assert chunks.c.auto_indexable.nullable is True
    assert isinstance(chunks.c.quality_issues.type, JSON)
    assert isinstance(chunks.c.extracted_metadata.type, JSON)

    embeddings = models.ChunkEmbedding.__table__
    assert embeddings.c.embedding.type.__class__.__name__ == "VECTOR"
    embedding_uniques = {
        tuple(column.name for column in constraint.columns)
        for constraint in embeddings.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert embedding_uniques == {("chunk_id", "provider_name", "model_name", "dimensions")}

    version = models.DocumentVersion(
        document_id=uuid4(),
        version_number=1,
        source_type="pasted_markdown",
        original_filename=None,
        raw_content="# Design",
        content_hash="a" * 64,
        status="processing",
    )
    job = models.IngestionJob(document_version=version)
    chunk = models.DocumentChunk(
        document_version=version,
        chunk_index=0,
        heading_path=["Design"],
        content="Content",
        content_hash="b" * 64,
        character_count=7,
    )
    assert version.ingestion_jobs == [job]
    assert version.chunks == [chunk]
    assert job.document_version is version
    assert chunk.document_version is version
    embedding = models.ChunkEmbedding(
        chunk=chunk,
        embedding=[0.1, 0.2],
        model_name="fake-embedding",
        dimensions=2,
        content_hash="b" * 64,
    )
    assert chunk.embeddings == [embedding]
    assert embedding.chunk is chunk


def test_document_models_do_not_prebuild_rag_or_agent_columns() -> None:
    documents = models.KnowledgeDocument.__table__
    versions = models.DocumentVersion.__table__

    prohibited_columns = {
        "published_at",
        "visibility",
        "normalized_content",
        "processed_at",
        "embedding",
        "reviewed_at",
    }
    assert prohibited_columns.isdisjoint(documents.columns.keys())
    assert prohibited_columns.isdisjoint(versions.columns.keys())
