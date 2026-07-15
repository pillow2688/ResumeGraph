import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update

from app.core.config import Settings
from app.infrastructure.database import Database
from app.infrastructure.embedding import FakeEmbeddingProvider
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
from app.schemas.access_grant import ProjectSummary, RecruiterPrincipal
from app.services.interview import INSUFFICIENT_EVIDENCE_ANSWER, InterviewService
from app.services.retrieval import RetrievalService

RUN_POSTGRES = os.getenv("RESUMEGRAPH_RUN_POSTGRES_INTEGRATION") == "1"


class DeterministicInterviewChatProvider:
    provider_name = "phase3-integration"
    model_name = "deterministic-chat"

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        del system_prompt
        payload = json.loads(user_prompt.split("\n上一次输出", 1)[0])
        question = payload["question"]
        evidence = payload["evidence"]
        if "QPS" in question or "P99" in question:
            return json.dumps(
                {
                    "status": "insufficient_evidence",
                    "answer": "资料不足",
                    "citation_handles": [],
                },
                ensure_ascii=False,
            )
        expected_text = "虚构大学" if "教育" in question else "Redis"
        selected = next(item for item in evidence if expected_text in item["content"])
        answer = (
            "我本科就读于虚构大学计算机专业，研究方向是可信人工智能。"
            if expected_text == "虚构大学"
            else "我在 ResumeGraph 中使用 Redis 保存短期 Session 和限流计数。"
        )
        return json.dumps(
            {
                "status": "answered",
                "answer": answer,
                "citation_handles": [selected["citation_handle"]],
            },
            ensure_ascii=False,
        )


async def _add_document(
    database: Database,
    provider: FakeEmbeddingProvider,
    *,
    project_id: UUID | None,
    title: str,
    content: str,
    published: bool = True,
    enabled: bool = True,
    matching_embedding_hash: bool = True,
    content_hash: str | None = None,
) -> tuple[UUID, UUID, UUID, UUID]:
    document_id, version_id, chunk_id, embedding_id = uuid4(), uuid4(), uuid4(), uuid4()
    actual_hash = content_hash or sha256(content.encode("utf-8")).hexdigest()
    vector = await provider.embed_query(content)
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
                heading_path=[title],
                content=content,
                content_hash=actual_hash,
                character_count=len(content),
                enabled=enabled,
                disabled_reason=None if enabled else "administrator",
                quality_issues=[],
                extracted_metadata={},
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
                content_hash=actual_hash if matching_embedding_hash else "f" * 64,
                embedding=vector,
            )
        )
        await session.commit()
        if published:
            await session.execute(
                update(KnowledgeDocument)
                .where(KnowledgeDocument.id == document_id)
                .values(current_published_version_id=version_id)
            )
            await session.commit()
    return document_id, version_id, chunk_id, embedding_id


async def _exercise_phase_3_postgres(settings: Settings) -> None:
    database = Database(settings.database_url.get_secret_value(), timeout_seconds=10)
    provider = FakeEmbeddingProvider(
        provider_name=settings.embedding_provider_name,
        model_name=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    project_ids = [uuid4(), uuid4(), uuid4()]
    grant_id = uuid4()
    document_ids: list[UUID] = []
    version_ids: list[UUID] = []
    chunk_ids: list[UUID] = []
    embedding_ids: list[UUID] = []
    education = "我本科就读于虚构大学计算机专业，研究方向是可信人工智能。"
    resumegraph = "我在 ResumeGraph 中使用 Redis 保存短期 Session 和限流计数。"
    education_hash = sha256(education.encode("utf-8")).hexdigest()
    try:
        async with database.session() as session:
            session.add_all(
                [
                    Project(id=project_ids[0], name="候选人简历与个人背景"),
                    Project(id=project_ids[1], name="ResumeGraph"),
                    Project(id=project_ids[2], name="未授权内部项目"),
                ]
            )
            session.add(
                AccessGrant(
                    id=grant_id,
                    name="Phase 3 fictional integration grant",
                    token_hash=f"phase3-integration-{grant_id}",
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                    max_requests=6,
                    request_count=0,
                )
            )
            await session.commit()
            session.add_all(
                [
                    GrantProject(grant_id=grant_id, project_id=project_ids[0]),
                    GrantProject(grant_id=grant_id, project_id=project_ids[1]),
                ]
            )
            await session.commit()

        specifications = [
            (None, "教育背景", education, True, True, True, education_hash),
            (project_ids[1], "ResumeGraph 设计", resumegraph, True, True, True, None),
            (project_ids[1], "补充教育摘录", "我关注可信人工智能方向。", True, True, True, None),
            (project_ids[2], "内部资料", "未授权的候选人私人信息。", True, True, True, None),
            (project_ids[0], "未发布资料", "尚未发布的技能资料。", False, True, True, None),
            (project_ids[0], "禁用资料", "已禁用的获奖资料。", True, False, True, None),
            (project_ids[0], "过期向量", "Embedding 哈希已经过期。", True, True, False, None),
        ]
        for (
            project_id,
            title,
            content,
            published,
            enabled,
            matching_hash,
            fixed_hash,
        ) in specifications:
            ids = await _add_document(
                database,
                provider,
                project_id=project_id,
                title=title,
                content=content,
                published=published,
                enabled=enabled,
                matching_embedding_hash=matching_hash,
                content_hash=fixed_hash,
            )
            document_ids.append(ids[0])
            version_ids.append(ids[1])
            chunk_ids.append(ids[2])
            embedding_ids.append(ids[3])

        repository = RetrievalRepository(database)
        education_results = await repository.search(
            grant_id=grant_id,
            query_embedding=await provider.embed_query(education),
            project_ids=project_ids[:2],
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            dimensions=provider.dimensions,
            top_k=10,
        )
        returned_ids = {record.chunk_id for record in education_results}
        assert education_results[0].distance == pytest.approx(0, abs=1e-6)
        assert education_results[0].document_scope == "profile"
        assert education_results[0].project_id is None
        assert sum(record.content_hash == education_hash for record in education_results) == 1
        assert chunk_ids[3] not in returned_ids
        assert chunk_ids[4] not in returned_ids
        assert chunk_ids[5] not in returned_ids
        assert chunk_ids[6] not in returned_ids

        unauthorized_project_search = await repository.search(
            grant_id=grant_id,
            query_embedding=await provider.embed_query("未授权的候选人私人信息。"),
            project_ids=[project_ids[2]],
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            dimensions=provider.dimensions,
            top_k=10,
        )
        assert unauthorized_project_search
        assert all(
            record.document_scope == "profile" and record.project_id is None
            for record in unauthorized_project_search
        )
        assert chunk_ids[3] not in {record.chunk_id for record in unauthorized_project_search}

        quota_repository = AccessGrantRepository(database)
        interview_service = InterviewService(
            quota_repository,
            RetrievalService(
                repository,
                provider,
                top_k=10,
                max_context_characters=12_000,
                dependency_timeout_seconds=10,
            ),
            DeterministicInterviewChatProvider(),
            output_retry_count=1,
            dependency_timeout_seconds=10,
        )
        principal = RecruiterPrincipal(
            grant_id=grant_id,
            grant_name="Phase 3 fictional integration grant",
            allowed_project_ids=project_ids[:2],
            grant_expires_at=datetime.now(UTC) + timedelta(hours=1),
            remaining_requests=6,
            allowed_projects=[
                ProjectSummary(id=project_ids[0], name="候选人简历与个人背景"),
                ProjectSummary(id=project_ids[1], name="ResumeGraph"),
            ],
        )
        education_answer = await interview_service.ask(
            principal=principal,
            question="请介绍你的教育背景和研究方向。",
            requested_project_ids=[project_ids[1]],
        )
        assert education_answer.status == "answered"
        assert education_answer.remaining_requests == 5
        assert education_answer.citations[0].document_scope == "profile"
        assert education_answer.citations[0].project_id is None
        assert education_answer.answer.startswith("我")

        project_answer = await interview_service.ask(
            principal=principal,
            question="为什么你在 ResumeGraph 中使用 Redis？",
            requested_project_ids=[project_ids[1]],
        )
        assert project_answer.status == "answered"
        assert project_answer.remaining_requests == 4
        assert project_answer.citations[0].project_id == project_ids[1]

        metric_answer = await interview_service.ask(
            principal=principal,
            question="ResumeGraph 的峰值 QPS 和 P99 延迟是多少？",
            requested_project_ids=[project_ids[1]],
        )
        assert metric_answer.status == "insufficient_evidence"
        assert metric_answer.answer == INSUFFICIENT_EVIDENCE_ANSWER
        assert metric_answer.citations == []
        assert metric_answer.remaining_requests == 3

        reservations = await asyncio.gather(
            *(quota_repository.consume_request(grant_id) for _ in range(12))
        )
        accepted = [reservation for reservation in reservations if reservation is not None]
        assert len(accepted) == 3
        async with database.session() as session:
            stored_count = (
                await session.execute(
                    select(AccessGrant.request_count).where(AccessGrant.id == grant_id)
                )
            ).scalar_one()
        assert stored_count == 6
        assert await quota_repository.consume_request(grant_id) is None

        async with database.session() as session:
            await session.execute(
                update(AccessGrant)
                .where(AccessGrant.id == grant_id)
                .values(revoked_at=datetime.now(UTC))
            )
            await session.commit()
        valid_after_revoke = await repository.revalidate(
            grant_id=grant_id,
            project_ids=project_ids[:2],
            chunk_ids=[education_results[0].chunk_id],
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            dimensions=provider.dimensions,
        )
        assert valid_after_revoke == set()
    finally:
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
            await session.execute(delete(GrantProject).where(GrantProject.grant_id == grant_id))
            await session.execute(delete(AccessGrant).where(AccessGrant.id == grant_id))
            await session.execute(delete(Project).where(Project.id.in_(project_ids)))
            await session.commit()
        await database.close()


@pytest.mark.skipif(
    not RUN_POSTGRES,
    reason="Set RESUMEGRAPH_RUN_POSTGRES_INTEGRATION=1 for the real PostgreSQL boundary.",
)
def test_real_profile_and_project_retrieval_and_atomic_concurrent_quota() -> None:
    asyncio.run(_exercise_phase_3_postgres(Settings()))
