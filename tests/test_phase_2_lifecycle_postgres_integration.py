import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.infrastructure.database import Database
from app.infrastructure.embedding import FakeEmbeddingProvider
from app.models import (
    ChunkEmbedding,
    DocumentChunk,
    DocumentVersion,
    IngestionJob,
    KnowledgeDocument,
    Project,
)
from app.repositories.deduplication import DeduplicationRepository
from app.repositories.knowledge_document import KnowledgeDocumentRepository
from app.repositories.knowledge_lifecycle import KnowledgeLifecycleRepository
from app.repositories.publication import PublicationRepository
from app.services.deduplication import DeduplicationService
from app.services.knowledge_lifecycle import KnowledgeLifecycleService
from app.services.publication import PublicationService

RUN_POSTGRES = os.getenv("RESUMEGRAPH_RUN_POSTGRES_INTEGRATION") == "1"
NOW = datetime(2026, 7, 15, 18, 0, tzinfo=UTC)
SHARED_HASH = "a" * 64


async def _add_published_document(
    database: Database,
    provider: FakeEmbeddingProvider,
    *,
    title: str,
    scope: str,
    project_id: UUID | None,
    created_at: datetime,
    content_hash: str = SHARED_HASH,
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    document_id = uuid4()
    version_id = uuid4()
    chunk_id = uuid4()
    embedding_id = uuid4()
    job_id = uuid4()
    vector = (await provider.embed_texts([f"Fictional evidence for {title}"]))[0]
    async with database.session() as session:
        session.add(
            KnowledgeDocument(
                id=document_id,
                project_id=project_id,
                document_scope=scope,
                title=title,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        await session.commit()
        session.add(
            DocumentVersion(
                id=version_id,
                document_id=document_id,
                version_number=1,
                source_type="pasted_markdown",
                original_filename=None,
                raw_content=f"# {title}\n\nFictional education evidence.",
                content_hash=str(uuid4()).replace("-", "") * 2,
                status="published",
                created_at=created_at,
            )
        )
        await session.commit()
        session.add(
            DocumentChunk(
                id=chunk_id,
                document_version_id=version_id,
                chunk_index=0,
                heading_path=["Education"],
                content="Fictional education evidence shared by two resumes.",
                content_hash=content_hash,
                character_count=53,
                enabled=True,
                disabled_reason=None,
                quality_issues=[],
                extracted_metadata={},
                created_at=created_at,
            )
        )
        await session.commit()
        session.add(
            ChunkEmbedding(
                id=embedding_id,
                chunk_id=chunk_id,
                provider_name=provider.provider_name,
                model_name=provider.model_name,
                dimensions=provider.dimensions,
                content_hash=content_hash,
                embedding=vector,
            )
        )
        session.add(
            IngestionJob(
                id=job_id,
                document_version_id=version_id,
                job_type="knowledge_indexing",
                status="completed",
                stage="saving",
                progress=100,
            )
        )
        await session.commit()
        await session.execute(
            update(KnowledgeDocument)
            .where(KnowledgeDocument.id == document_id)
            .values(current_published_version_id=version_id)
        )
        await session.commit()
    return document_id, version_id, chunk_id, embedding_id, job_id


async def _exercise_lifecycle(settings: Settings) -> None:
    database = Database(settings.database_url.get_secret_value(), timeout_seconds=10)
    provider = FakeEmbeddingProvider(
        provider_name=settings.embedding_provider_name,
        model_name=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    deduplication = DeduplicationService(
        DeduplicationRepository(database),
        provider,
        dependency_timeout_seconds=10,
    )
    publication = PublicationService(
        PublicationRepository(database),
        provider_name=provider.provider_name,
        model_name=provider.model_name,
        dimensions=provider.dimensions,
        dependency_timeout_seconds=10,
        deduplication_service=deduplication,
    )
    lifecycle = KnowledgeLifecycleService(
        KnowledgeLifecycleRepository(database),
        deduplication,
        dependency_timeout_seconds=10,
    )
    project_ids = [uuid4(), uuid4()]
    document_ids: list[UUID] = []
    try:
        async with database.session() as session:
            session.add_all(
                [
                    Project(id=project_ids[0], name=f"Lifecycle project A {project_ids[0]}"),
                    Project(id=project_ids[1], name=f"Lifecycle project B {project_ids[1]}"),
                ]
            )
            await session.commit()

        for invalid in (
            KnowledgeDocument(
                id=uuid4(),
                project_id=project_ids[0],
                document_scope="profile",
                title="Invalid profile scope",
            ),
            KnowledgeDocument(
                id=uuid4(),
                project_id=None,
                document_scope="project",
                title="Invalid project scope",
            ),
        ):
            async with database.session() as session:
                session.add(invalid)
                with pytest.raises(IntegrityError):
                    await session.commit()
                await session.rollback()

        profile_a = await _add_published_document(
            database,
            provider,
            title="Fictional profile A",
            scope="profile",
            project_id=None,
            created_at=NOW,
        )
        profile_b = await _add_published_document(
            database,
            provider,
            title="Fictional profile B",
            scope="profile",
            project_id=None,
            created_at=NOW + timedelta(seconds=1),
        )
        document_ids.extend([profile_a[0], profile_b[0]])

        result = await deduplication.rebuild_profile_scope()
        assert result.canonical_count == 1
        assert result.duplicate_count == 1
        async with database.session() as session:
            chunks = {
                item.id: item
                for item in (
                    await session.execute(
                        select(DocumentChunk).where(
                            DocumentChunk.id.in_([profile_a[2], profile_b[2]])
                        )
                    )
                ).scalars()
            }
            assert chunks[profile_a[2]].enabled is True
            assert chunks[profile_a[2]].disabled_reason is None
            assert chunks[profile_b[2]].enabled is False
            assert chunks[profile_b[2]].disabled_reason == "exact_duplicate"
            embedding_count = (
                await session.execute(
                    select(func.count(ChunkEmbedding.id)).where(
                        ChunkEmbedding.chunk_id.in_([profile_a[2], profile_b[2]])
                    )
                )
            ).scalar_one()
            assert embedding_count == 1

        project_documents = []
        for offset, project_id in enumerate(project_ids, start=2):
            item = await _add_published_document(
                database,
                provider,
                title=f"Fictional project profile {offset}",
                scope="project",
                project_id=project_id,
                created_at=NOW + timedelta(seconds=offset),
            )
            document_ids.append(item[0])
            project_documents.append(item)
            await deduplication.rebuild_project_scope(project_id)
        async with database.session() as session:
            project_chunks = (
                (
                    await session.execute(
                        select(DocumentChunk).where(
                            DocumentChunk.id.in_([item[2] for item in project_documents])
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(project_chunks) == 2
            assert all(item.enabled for item in project_chunks)

        version_two_id = uuid4()
        version_two_chunk_id = uuid4()
        version_two_embedding_id = uuid4()
        vector = (await provider.embed_texts(["Fictional replacement resume."]))[0]
        async with database.session() as session:
            session.add(
                DocumentVersion(
                    id=version_two_id,
                    document_id=profile_b[0],
                    version_number=2,
                    source_type="pasted_markdown",
                    original_filename=None,
                    raw_content="# Fictional profile B v2",
                    content_hash="b" * 64,
                    status="ready_to_publish",
                    created_at=NOW + timedelta(seconds=5),
                )
            )
            await session.commit()
            session.add(
                DocumentChunk(
                    id=version_two_chunk_id,
                    document_version_id=version_two_id,
                    chunk_index=0,
                    heading_path=["Education"],
                    content="Fictional education evidence shared by two resumes.",
                    content_hash=SHARED_HASH,
                    character_count=53,
                    enabled=True,
                    disabled_reason=None,
                    quality_issues=[],
                    extracted_metadata={},
                    created_at=NOW + timedelta(seconds=5),
                )
            )
            await session.commit()
            session.add(
                ChunkEmbedding(
                    id=version_two_embedding_id,
                    chunk_id=version_two_chunk_id,
                    provider_name=provider.provider_name,
                    model_name=provider.model_name,
                    dimensions=provider.dimensions,
                    content_hash=SHARED_HASH,
                    embedding=vector,
                )
            )
            await session.commit()

        before_publish = await PublicationRepository(database).publish_version(
            version_two_id,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            dimensions=provider.dimensions,
        )
        assert before_publish is not None
        await deduplication.rebuild_profile_scope()
        listed_profiles = await KnowledgeDocumentRepository(database).list_profile_documents()
        listed_profile_b = next(item for item in listed_profiles if item.id == profile_b[0])
        assert listed_profile_b.current_published_version_id == version_two_id
        assert listed_profile_b.current_published_version_number == 2
        async with database.session() as session:
            old_version = (
                await session.execute(
                    select(DocumentVersion).where(DocumentVersion.id == profile_b[1])
                )
            ).scalar_one()
            new_version = (
                await session.execute(
                    select(DocumentVersion).where(DocumentVersion.id == version_two_id)
                )
            ).scalar_one()
            assert old_version.status == "superseded"
            assert new_version.status == "published"

        await lifecycle.delete_version(profile_b[1])
        async with database.session() as session:
            assert (
                await session.execute(
                    select(DocumentVersion).where(DocumentVersion.id == profile_b[1])
                )
            ).scalar_one_or_none() is None
            assert (
                await session.execute(select(IngestionJob).where(IngestionJob.id == profile_b[4]))
            ).scalar_one_or_none() is None

        await lifecycle.delete_document(profile_a[0], confirmation="Fictional profile A")
        async with database.session() as session:
            assert (
                await session.execute(
                    select(KnowledgeDocument).where(KnowledgeDocument.id == profile_a[0])
                )
            ).scalar_one_or_none() is None
            assert (
                await session.execute(
                    select(DocumentVersion).where(DocumentVersion.id == profile_a[1])
                )
            ).scalar_one_or_none() is None
            assert (
                await session.execute(select(IngestionJob).where(IngestionJob.id == profile_a[4]))
            ).scalar_one_or_none() is None
            promoted = (
                await session.execute(
                    select(DocumentChunk).where(DocumentChunk.id == version_two_chunk_id)
                )
            ).scalar_one()
            assert promoted.enabled is True
            assert promoted.disabled_reason is None
            promoted_embeddings = (
                await session.execute(
                    select(func.count(ChunkEmbedding.id)).where(
                        ChunkEmbedding.chunk_id == version_two_chunk_id
                    )
                )
            ).scalar_one()
            assert promoted_embeddings == 1

        await publication.unpublish_document(profile_b[0])
        async with database.session() as session:
            retained_document = (
                await session.execute(
                    select(KnowledgeDocument).where(KnowledgeDocument.id == profile_b[0])
                )
            ).scalar_one()
            assert retained_document.current_published_version_id is None
            assert (
                await session.execute(
                    select(DocumentVersion).where(DocumentVersion.id == version_two_id)
                )
            ).scalar_one_or_none() is not None
            assert (
                await session.execute(
                    select(DocumentChunk).where(DocumentChunk.id == version_two_chunk_id)
                )
            ).scalar_one_or_none() is not None
            assert (
                await session.execute(
                    select(ChunkEmbedding).where(ChunkEmbedding.chunk_id == version_two_chunk_id)
                )
            ).scalar_one_or_none() is not None

        await lifecycle.delete_document(profile_b[0], confirmation="Fictional profile B")
        async with database.session() as session:
            assert (
                await session.execute(
                    select(KnowledgeDocument).where(KnowledgeDocument.id == profile_b[0])
                )
            ).scalar_one_or_none() is None
            assert (
                await session.execute(
                    select(DocumentChunk).where(DocumentChunk.id == version_two_chunk_id)
                )
            ).scalar_one_or_none() is None
            assert (
                await session.execute(
                    select(ChunkEmbedding).where(ChunkEmbedding.id == version_two_embedding_id)
                )
            ).scalar_one_or_none() is None
    finally:
        async with database.session() as session:
            await session.execute(
                update(KnowledgeDocument)
                .where(KnowledgeDocument.id.in_(document_ids))
                .values(current_published_version_id=None)
            )
            await session.execute(
                delete(KnowledgeDocument).where(KnowledgeDocument.id.in_(document_ids))
            )
            await session.execute(delete(Project).where(Project.id.in_(project_ids)))
            await session.commit()
        await database.close()


@pytest.mark.skipif(
    not RUN_POSTGRES,
    reason="Set RESUMEGRAPH_RUN_POSTGRES_INTEGRATION=1 for the real lifecycle boundary.",
)
def test_real_postgresql_profile_project_deduplication_and_cascading_lifecycle() -> None:
    asyncio.run(_exercise_lifecycle(Settings()))
