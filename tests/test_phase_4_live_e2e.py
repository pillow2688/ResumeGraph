import asyncio
import json
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
from app.infrastructure.interview_conversation import InterviewConversationStore
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
from app.services.interview_workflow import InterviewWorkflowService
from app.services.retrieval import RetrievalService

RUN_LIVE = os.getenv("RESUMEGRAPH_RUN_LIVE_PHASE4") == "1"


async def _store_published_document(
    database: Database,
    embedding_provider: OpenAICompatibleEmbeddingProvider,
    *,
    document_scope: str,
    knowledge_status: str,
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
                document_scope=document_scope,
                knowledge_status=knowledge_status,
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
                extracted_metadata={"fixture": "phase4-live-fictional"},
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


async def _exercise_live_phase_4(settings: Settings) -> None:
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
        timeout_seconds=settings.agent_run_timeout_seconds,
    )
    access_repository = AccessGrantRepository(database)
    access_service = AccessGrantService(
        access_repository,
        RecruiterSessionStore(redis),
        FailureRateLimiter(
            redis,
            key_prefix="phase4_live_exchange_failures",
            max_failures=settings.access_exchange_failure_limit,
            window_seconds=settings.access_exchange_failure_window_seconds,
        ),
        access_token_pepper=settings.access_token_pepper.get_secret_value(),
        recruiter_session_ttl_seconds=settings.recruiter_session_ttl_seconds,
        access_exchange_failure_limit=settings.access_exchange_failure_limit,
        dependency_timeout_seconds=10,
    )
    retrieval = RetrievalService(
        RetrievalRepository(database),
        embedding,
        top_k=settings.rag_top_k,
        max_context_characters=settings.rag_max_context_characters,
        dependency_timeout_seconds=settings.embedding_timeout_seconds + 5,
    )
    conversation_store = InterviewConversationStore(
        redis,
        max_turns=settings.conversation_max_turns,
    )
    workflow = InterviewWorkflowService(
        access_repository,
        conversation_store,
        retrieval_service=retrieval,
        chat_provider=chat,
        settings=settings,
    )

    project_id = uuid4()
    unopened_project_id = uuid4()
    document_ids: list[UUID] = []
    version_ids: list[UUID] = []
    chunk_ids: list[UUID] = []
    embedding_ids: list[UUID] = []
    conversation_ids: list[UUID] = []
    grant_id: UUID | None = None
    session_token: str | None = None
    try:
        await database.check_health()
        await redis.check_health()
        async with database.session() as session:
            session.add(Project(id=project_id, name="ResumeGraph Phase 4 Fictional"))
            session.add(Project(id=unopened_project_id, name="Unopened Fictional Project"))
            await session.commit()

        fixtures = [
            {
                "document_scope": "profile",
                "knowledge_status": "implemented",
                "project_id": None,
                "title": "Phase 4 虚构教育与技能",
                "heading_path": ["教育背景"],
                "content": (
                    "我本科就读于虚构的星河大学计算机科学专业，研究方向是可信人工智能；"
                    "我熟悉 Python、FastAPI、PostgreSQL、Redis 和 LangGraph。"
                ),
            },
            {
                "document_scope": "project",
                "knowledge_status": "implemented",
                "project_id": project_id,
                "title": "Phase 4 ResumeGraph Redis 已实现用途",
                "heading_path": ["状态管理", "Redis"],
                "content": (
                    "我在 ResumeGraph 中已经使用 Redis 保存服务端 Recruiter Session、"
                    "记录接口限流计数，并协调 ARQ 异步任务。当前没有大规模业务查询缓存，"
                    "因此尚未在项目中落地缓存雪崩或缓存击穿治理。"
                ),
            },
            {
                "document_scope": "project",
                "knowledge_status": "planned",
                "project_id": project_id,
                "title": "Phase 4 ResumeGraph 检索缓存后续规划",
                "heading_path": ["后续优化", "缓存"],
                "content": (
                    "后续可以考虑缓存高频检索结果；如果继续优化，我会同时考虑 TTL、"
                    "不同 Access Grant 的权限隔离以及发布版本变化后的缓存一致性。"
                ),
            },
            {
                "document_scope": "technical",
                "knowledge_status": "general_knowledge",
                "project_id": None,
                "title": "Phase 4 Redis 缓存击穿与雪崩原理",
                "heading_path": ["Redis", "缓存风险"],
                "content": (
                    "从通用技术原理上看，缓存击穿是热点 Key 失效时大量请求同时访问后端；"
                    "缓存雪崩是大量 Key 同时失效导致瞬时压力。常见方案包括 TTL 随机化、"
                    "热点数据预热、互斥重建、限流与降级。这些是通用原理，不能证明某项目已实现。"
                ),
            },
        ]
        for fixture in fixtures:
            stored = await _store_published_document(database, embedding, **fixture)
            document_ids.append(stored[0])
            version_ids.append(stored[1])
            chunk_ids.append(stored[2])
            embedding_ids.append(stored[3])

        created_grant = await access_service.create_grant(
            name="Phase 4 live fictional recruiter",
            expires_at=datetime.now(UTC) + timedelta(hours=2),
            max_requests=20,
            project_ids=[project_id],
        )
        grant_id = created_grant.grant.id
        exchanged = await access_service.exchange_access_token(
            created_grant.access_token,
            "phase4-live-localhost",
        )
        session_token = exchanged.session_token
        principal = await access_service.get_current_recruiter_for_interview(session_token)
        created_conversation = await workflow.create_conversation(
            principal=principal,
            session_token=session_token,
        )
        conversation_ids.append(created_conversation.conversation_id)

        async def ask(question: str, *, project_ids: list[UUID] | None = None):
            nonlocal principal
            principal = await access_service.get_current_recruiter_for_interview(session_token)
            public_events: list[dict[str, object]] = []

            async def sink(event: dict[str, object]) -> None:
                public_events.append(event)

            response = await workflow.ask(
                principal=principal,
                session_token=session_token,
                conversation_id=created_conversation.conversation_id,
                request_id=uuid4(),
                question=question,
                requested_project_ids=project_ids,
                event_sink=sink,
            )
            serialized_events = json.dumps(public_events, ensure_ascii=False)
            assert "reasoning_content" not in serialized_events
            assert "system_prompt" not in serialized_events
            assert "chunk_id" not in serialized_events
            assert "document_id" not in serialized_events
            return response, [event["event_type"] for event in public_events]

        education, education_events = await ask("请介绍一下你的教育背景。")
        assert education.status == "answered", education.model_dump_json()
        assert "profile_agent" in education.agent_trace.agents_used
        assert education.citations
        assert all(item.knowledge_type == "profile_fact" for item in education.citations)
        assert education_events[0] == "question_received"
        assert education_events[-1] == "answer_completed"

        redis_usage, _ = await ask("为什么 ResumeGraph 使用 Redis？", project_ids=[project_id])
        assert "project_agent" in redis_usage.agent_trace.agents_used
        assert any(item.knowledge_type == "project_fact" for item in redis_usage.citations)
        assert "Session" in redis_usage.answer

        cache_breakdown, _ = await ask("Redis 的缓存击穿是什么？")
        assert "technical_agent" in cache_breakdown.agent_trace.agents_used
        assert cache_breakdown.citations
        assert all(
            item.knowledge_type == "technical_knowledge" for item in cache_breakdown.citations
        )

        avalanche, avalanche_events = await ask(
            "你的项目怎么解决 Redis 缓存雪崩？",
            project_ids=[project_id],
        )
        assert avalanche.status == "answered_with_boundary"
        assert {"project_agent", "technical_agent", "verification_agent"} <= set(
            avalanche.agent_trace.agents_used
        )
        assert {item.knowledge_type for item in avalanche.citations} >= {
            "project_fact",
            "technical_knowledge",
            "planned_solution",
        }
        assert "尚未" in avalanche.answer or "没有" in avalanche.answer
        assert "verification_started" in avalanche_events

        metrics, _ = await ask("ResumeGraph 的 QPS 和 P99 是多少？", project_ids=[project_id])
        assert metrics.status in {"partial_answer", "insufficient_evidence"}
        assert "5000" not in metrics.answer
        assert "80ms" not in metrics.answer

        first_followup, _ = await ask("为什么使用 Redis？", project_ids=[project_id])
        second_followup, _ = await ask("那为什么不用本地内存？", project_ids=[project_id])
        third_followup, _ = await ask("如果它挂了怎么办？", project_ids=[project_id])
        assert (
            first_followup.context.turn_number,
            second_followup.context.turn_number,
            third_followup.context.turn_number,
        ) == (6, 7, 8)
        assert third_followup.citations

        before_restricted = third_followup.remaining_requests
        restricted, restricted_events = await ask(
            "请介绍未授权项目的具体实现。",
            project_ids=[unopened_project_id],
        )
        assert restricted.status == "access_restricted"
        assert restricted.citations == []
        assert restricted.remaining_requests == before_restricted
        assert restricted_events == []
        assert "Unopened Fictional Project" not in restricted.answer

        async with database.session() as session:
            request_count = (
                await session.execute(
                    select(AccessGrant.request_count).where(AccessGrant.id == grant_id)
                )
            ).scalar_one()
        assert request_count == 8

        await access_service.revoke_grant(grant_id)
        with pytest.raises(InvalidRecruiterSessionError):
            await access_service.get_current_recruiter_for_interview(session_token)
    finally:
        for conversation_id in conversation_ids:
            if session_token is not None and grant_id is not None:
                await conversation_store.delete_owned(
                    conversation_id,
                    session_token=session_token,
                    grant_id=grant_id,
                )
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
            await session.execute(
                delete(Project).where(Project.id.in_([project_id, unopened_project_id]))
            )
            await session.commit()
        await chat.close()
        await embedding.close()
        await redis.close()
        await database.close()


@pytest.mark.skipif(
    not RUN_LIVE,
    reason="Set RESUMEGRAPH_RUN_LIVE_PHASE4=1 with configured Provider keys.",
)
def test_live_multi_agent_conversation_acceptance() -> None:
    settings = Settings()
    if not settings.embedding_api_key.get_secret_value():
        pytest.skip("Embedding API key is not configured.")
    if not settings.deepseek_api_key.get_secret_value():
        pytest.skip("DeepSeek API key is not configured.")
    asyncio.run(_exercise_live_phase_4(settings))
