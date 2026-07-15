import asyncio
import os
from collections.abc import Sequence
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select, update

from app.core.config import Settings
from app.infrastructure.database import Database
from app.infrastructure.embedding import (
    FakeEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)
from app.models import (
    ChunkEmbedding,
    DocumentChunk,
    DocumentVersion,
    KnowledgeDocument,
    Project,
)
from app.repositories.publication import PublicationRepository

RUN_POSTGRES = os.getenv("RESUMEGRAPH_RUN_POSTGRES_INTEGRATION") == "1"
RUN_LIVE = os.getenv("RESUMEGRAPH_RUN_LIVE_EMBEDDING") == "1"


async def _exercise_pgvector_and_publication(
    *,
    vector: Sequence[float],
    settings: Settings,
) -> None:
    database = Database(
        settings.database_url.get_secret_value(),
        timeout_seconds=10,
    )
    project_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    chunk_id = uuid4()
    embedding_id = uuid4()
    try:
        async with database.session() as session:
            session.add(Project(id=project_id, name=f"Phase 2.4 integration {project_id}"))
            await session.commit()
            session.add(
                KnowledgeDocument(
                    id=document_id,
                    project_id=project_id,
                    title="Fictional integration document",
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
                    raw_content="# Fictional architecture\n\nUses bounded retries.",
                    content_hash="a" * 64,
                    status="ready_to_publish",
                )
            )
            await session.commit()
            session.add(
                DocumentChunk(
                    id=chunk_id,
                    document_version_id=version_id,
                    chunk_index=0,
                    heading_path=["Fictional architecture"],
                    content="Uses bounded retries.",
                    content_hash="b" * 64,
                    character_count=21,
                    enabled=True,
                )
            )
            await session.commit()
            session.add(
                ChunkEmbedding(
                    id=embedding_id,
                    chunk_id=chunk_id,
                    provider_name=settings.embedding_provider_name,
                    model_name=settings.embedding_model,
                    dimensions=settings.embedding_dimensions,
                    content_hash="b" * 64,
                    embedding=list(vector),
                )
            )
            await session.commit()

        repository = PublicationRepository(database)
        published = await repository.publish_version(
            version_id,
            provider_name=settings.embedding_provider_name,
            model_name=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )
        assert published is not None
        assert published.current_published_version_id == version_id

        async with database.session() as session:
            stored = (
                await session.execute(
                    select(ChunkEmbedding).where(ChunkEmbedding.id == embedding_id)
                )
            ).scalar_one()
            document = (
                await session.execute(
                    select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
                )
            ).scalar_one()
            version = (
                await session.execute(
                    select(DocumentVersion).where(DocumentVersion.id == version_id)
                )
            ).scalar_one()
            assert len(stored.embedding) == settings.embedding_dimensions
            assert stored.provider_name == settings.embedding_provider_name
            assert stored.model_name == settings.embedding_model
            assert stored.content_hash == "b" * 64
            assert document.current_published_version_id == version_id
            assert version.status == "published"

        unpublished = await repository.unpublish_document(document_id)
        assert unpublished is not None
        assert unpublished.current_published_version_id is None
    finally:
        async with database.session() as session:
            await session.execute(
                update(KnowledgeDocument)
                .where(KnowledgeDocument.id == document_id)
                .values(current_published_version_id=None)
            )
            await session.execute(delete(ChunkEmbedding).where(ChunkEmbedding.id == embedding_id))
            await session.execute(delete(DocumentChunk).where(DocumentChunk.id == chunk_id))
            await session.execute(delete(DocumentVersion).where(DocumentVersion.id == version_id))
            await session.execute(
                delete(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
            )
            await session.execute(delete(Project).where(Project.id == project_id))
            await session.commit()
        await database.close()


@pytest.mark.skipif(
    not RUN_POSTGRES,
    reason="Set RESUMEGRAPH_RUN_POSTGRES_INTEGRATION=1 for the real PostgreSQL boundary.",
)
def test_real_postgresql_pgvector_write_publish_and_unpublish() -> None:
    settings = Settings()
    fake = FakeEmbeddingProvider(
        provider_name=settings.embedding_provider_name,
        model_name=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    vector = asyncio.run(fake.embed_texts(["Fictional architecture with bounded retries."]))[0]

    asyncio.run(_exercise_pgvector_and_publication(vector=vector, settings=settings))


@pytest.mark.skipif(
    not RUN_LIVE,
    reason="Set RESUMEGRAPH_RUN_LIVE_EMBEDDING=1 and EMBEDDING_API_KEY for live API use.",
)
def test_live_openai_compatible_embedding_pgvector_and_publication() -> None:
    settings = Settings()
    if not settings.embedding_api_key.get_secret_value():
        pytest.skip("EMBEDDING_API_KEY is not configured.")
    provider = OpenAICompatibleEmbeddingProvider(
        provider_name=settings.embedding_provider_name,
        api_key=SecretStr(settings.embedding_api_key.get_secret_value()),
        base_url=settings.embedding_base_url,
        model_name=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        send_dimensions=settings.embedding_send_dimensions,
        batch_size=settings.embedding_batch_size,
        timeout_seconds=settings.embedding_timeout_seconds,
        max_retries=settings.embedding_max_retries,
    )

    async def run() -> None:
        try:
            vector = (
                await provider.embed_texts(
                    ["Fictional public architecture: FastAPI worker with bounded retries."]
                )
            )[0]
            await _exercise_pgvector_and_publication(vector=vector, settings=settings)
        finally:
            await provider.close()

    asyncio.run(run())
