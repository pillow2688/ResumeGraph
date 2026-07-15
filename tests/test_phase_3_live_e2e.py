import asyncio
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select, update

from app.core.config import Settings
from app.infrastructure.chat import OpenAICompatibleChatProvider
from app.infrastructure.database import Database
from app.infrastructure.embedding import OpenAICompatibleEmbeddingProvider
from app.infrastructure.failure_limiter import FailureRateLimiter
from app.infrastructure.recruiter_session import RecruiterSessionStore
from app.infrastructure.redis import RedisConnection
from app.models import (
    AccessGrant,
    ChunkEmbedding,
    DocumentChunk,
    DocumentVersion,
    GrantProject,
    KnowledgeDocument,
    Project,
)
from app.repositories.access_grant import AccessGrantRepository
from app.repositories.retrieval import RetrievalRepository
from app.services.access_grant import AccessGrantService, InvalidRecruiterSessionError
from app.services.interview import InterviewService
from app.services.retrieval import RetrievalService

RUN_LIVE = os.getenv("RESUMEGRAPH_RUN_LIVE_PHASE3") == "1"


async def _store_published_document(
    database: Database,
    embedding_provider: OpenAICompatibleEmbeddingProvider,
    *,
    project_id: UUID | None,
    title: str,
    heading_path: list[str],
    content: str,
) -> tuple[UUID, UUID, UUID, UUID]:
    document_id, version_id, chunk_id, embedding_id = uuid4(), uuid4(), uuid4(), uuid4()
    content_hash = sha256(content.encode("utf-8")).hexdigest()
    vector = await embedding_provider.embed_query(content)
    async with database.session() as session:
        session.add(
            KnowledgeDocument(
                id=document_id,
                project_id=project_id,
                document_scope="profile" if project_id is None else "project",
                title=title,
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
                raw_content=content,
                content_hash=sha256(f"version:{document_id}:{content}".encode()).hexdigest(),
                status="published",
            )
        )
        await session.commit()
        session.add(
            DocumentChunk(
                id=chunk_id,
                document_version_id=version_id,
                chunk_index=0,
                heading_path=heading_path,
                content=content,
                content_hash=content_hash,
                character_count=len(content),
                enabled=True,
                disabled_reason=None,
                quality_issues=[],
                extracted_metadata={},
            )
        )
        await session.commit()
        session.add(
            ChunkEmbedding(
                id=embedding_id,
                chunk_id=chunk_id,
                provider_name=embedding_provider.provider_name,
                model_name=embedding_provider.model_name,
                dimensions=embedding_provider.dimensions,
                content_hash=content_hash,
                embedding=vector,
            )
        )
        await session.commit()
        await session.execute(
            update(KnowledgeDocument)
            .where(KnowledgeDocument.id == document_id)
            .values(current_published_version_id=version_id)
        )
        await session.commit()
    return document_id, version_id, chunk_id, embedding_id


async def _exercise_live_phase_3(settings: Settings) -> None:
    database = Database(settings.database_url.get_secret_value(), timeout_seconds=10)
    redis = RedisConnection(settings.redis_url.get_secret_value(), timeout_seconds=10)
    embedding = OpenAICompatibleEmbeddingProvider(
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
    chat = OpenAICompatibleChatProvider(
        provider_name="deepseek",
        api_key=SecretStr(settings.deepseek_api_key.get_secret_value()),
        base_url=settings.deepseek_base_url,
        model_name=settings.deepseek_quality_model,
        timeout_seconds=settings.rag_answer_timeout_seconds,
    )
    access_repository = AccessGrantRepository(database)
    access_service = AccessGrantService(
        access_repository,
        RecruiterSessionStore(redis),
        FailureRateLimiter(
            redis,
            key_prefix="phase3_live_exchange_failures",
            max_failures=settings.access_exchange_failure_limit,
            window_seconds=settings.access_exchange_failure_window_seconds,
        ),
        access_token_pepper=settings.access_token_pepper.get_secret_value(),
        recruiter_session_ttl_seconds=settings.recruiter_session_ttl_seconds,
        access_exchange_failure_limit=settings.access_exchange_failure_limit,
        dependency_timeout_seconds=10,
    )
    interview = InterviewService(
        access_repository,
        RetrievalService(
            RetrievalRepository(database),
            embedding,
            top_k=settings.rag_top_k,
            max_context_characters=settings.rag_max_context_characters,
            dependency_timeout_seconds=settings.embedding_timeout_seconds + 5,
        ),
        chat,
        output_retry_count=settings.rag_answer_output_retries,
        dependency_timeout_seconds=settings.rag_answer_timeout_seconds + 5,
    )
    project_ids = [uuid4()]
    document_ids: list[UUID] = []
    version_ids: list[UUID] = []
    chunk_ids: list[UUID] = []
    embedding_ids: list[UUID] = []
    grant_id: UUID | None = None
    session_token: str | None = None
    try:
        await database.check_health()
        await redis.check_health()
        async with database.session() as session:
            session.add(Project(id=project_ids[0], name="ResumeGraph"))
            await session.commit()

        stored = await _store_published_document(
            database,
            embedding,
            project_id=None,
            title="教育、技能与个人简介",
            heading_path=["教育背景"],
            content=(
                "我本科就读于虚构大学计算机科学专业，研究方向是可信人工智能；"
                "我熟悉 Python、FastAPI、PostgreSQL 和 Redis。"
            ),
        )
        document_ids.append(stored[0])
        version_ids.append(stored[1])
        chunk_ids.append(stored[2])
        embedding_ids.append(stored[3])
        stored = await _store_published_document(
            database,
            embedding,
            project_id=project_ids[0],
            title="ResumeGraph 项目设计文档",
            heading_path=["访问控制", "Redis"],
            content=(
                "我在 ResumeGraph 中让 PostgreSQL 作为授权事实来源，"
                "Redis 只保存短期 Recruiter Session 和限流计数。"
            ),
        )
        document_ids.append(stored[0])
        version_ids.append(stored[1])
        chunk_ids.append(stored[2])
        embedding_ids.append(stored[3])

        created = await access_service.create_grant(
            name="Phase 3 live fictional recruiter",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            max_requests=10,
            project_ids=project_ids,
        )
        grant_id = created.grant.id
        exchanged = await access_service.exchange_access_token(
            created.access_token,
            "phase3-live-localhost",
        )
        session_token = exchanged.session_token
        principal = await access_service.get_current_recruiter_for_interview(session_token)

        education_answer = await interview.ask(
            principal=principal,
            question="你的教育背景和研究方向是什么？",
            requested_project_ids=[project_ids[0]],
        )
        assert education_answer.status == "answered"
        assert education_answer.citations
        assert education_answer.citations[0].document_scope == "profile"
        assert education_answer.citations[0].project_id is None
        assert "我" in education_answer.answer

        principal = await access_service.get_current_recruiter_for_interview(session_token)
        project_answer = await interview.ask(
            principal=principal,
            question="为什么你在 ResumeGraph 中使用 Redis？",
            requested_project_ids=[project_ids[0]],
        )
        assert project_answer.status == "answered"
        assert project_answer.citations[0].project_id == project_ids[0]
        assert "我" in project_answer.answer

        principal = await access_service.get_current_recruiter_for_interview(session_token)
        missing_metric = await interview.ask(
            principal=principal,
            question="ResumeGraph 经测试的峰值 QPS 和 P99 延迟分别是多少？",
            requested_project_ids=[project_ids[0]],
        )
        assert missing_metric.status == "insufficient_evidence"
        assert missing_metric.citations == []

        async with database.session() as session:
            request_count = (
                await session.execute(
                    select(AccessGrant.request_count).where(AccessGrant.id == grant_id)
                )
            ).scalar_one()
        assert request_count == 3

        await access_service.revoke_grant(grant_id)
        with pytest.raises(InvalidRecruiterSessionError):
            await access_service.get_current_recruiter_for_interview(session_token)
    finally:
        if session_token is not None:
            await access_service.logout(session_token)
        async with database.session() as session:
            if document_ids:
                await session.execute(
                    update(KnowledgeDocument)
                    .where(KnowledgeDocument.id.in_(document_ids))
                    .values(current_published_version_id=None)
                )
                await session.execute(
                    delete(ChunkEmbedding).where(ChunkEmbedding.id.in_(embedding_ids))
                )
                await session.execute(delete(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids)))
                await session.execute(
                    delete(DocumentVersion).where(DocumentVersion.id.in_(version_ids))
                )
                await session.execute(
                    delete(KnowledgeDocument).where(KnowledgeDocument.id.in_(document_ids))
                )
            if grant_id is not None:
                await session.execute(delete(GrantProject).where(GrantProject.grant_id == grant_id))
                await session.execute(delete(AccessGrant).where(AccessGrant.id == grant_id))
            await session.execute(delete(Project).where(Project.id.in_(project_ids)))
            await session.commit()
        await chat.close()
        await embedding.close()
        await redis.close()
        await database.close()


@pytest.mark.skipif(
    not RUN_LIVE,
    reason="Set RESUMEGRAPH_RUN_LIVE_PHASE3=1 with configured Provider keys.",
)
def test_live_single_turn_rag_recruiter_acceptance() -> None:
    settings = Settings()
    if not settings.embedding_api_key.get_secret_value():
        pytest.skip("Embedding API key is not configured.")
    if not settings.deepseek_api_key.get_secret_value():
        pytest.skip("DeepSeek API key is not configured.")
    asyncio.run(_exercise_live_phase_3(settings))
