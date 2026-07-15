import logging
import math
from typing import Any, cast
from uuid import UUID

from arq.connections import RedisSettings
from arq.worker import func

from app.core.config import Settings
from app.infrastructure.database import Database
from app.infrastructure.deepseek_quality import (
    DeepSeekQualityProvider,
    UnconfiguredQualityProvider,
)
from app.infrastructure.embedding import (
    OpenAICompatibleEmbeddingProvider,
    UnconfiguredEmbeddingProvider,
)
from app.infrastructure.job_queue import (
    INGESTION_QUEUE_NAME,
    json_deserializer,
    json_serializer,
)
from app.quality.rules import RuleConfig
from app.repositories.indexing import IndexingRepository
from app.repositories.ingestion import IngestionRepository
from app.services.indexing_worker import IndexingWorker
from app.services.ingestion_worker import IngestionWorker

logger = logging.getLogger(__name__)


async def worker_startup(context: dict[str, Any]) -> None:
    settings = cast(Settings, context.get("settings")) if "settings" in context else Settings()
    database = Database(
        settings.database_url.get_secret_value(),
        timeout_seconds=settings.dependency_timeout_seconds,
    )
    context["database"] = database
    context["ingestion_worker"] = IngestionWorker(
        IngestionRepository(database),
        chunk_max_characters=settings.chunk_max_characters,
    )
    quality_provider = (
        DeepSeekQualityProvider(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_quality_model,
            timeout_seconds=settings.quality_judge_timeout_seconds,
            max_retries=settings.quality_judge_max_retries,
            batch_size=settings.quality_judge_batch_size,
            thinking_enabled=settings.deepseek_quality_thinking_enabled,
        )
        if settings.deepseek_api_key.get_secret_value()
        else UnconfiguredQualityProvider()
    )
    context["quality_provider"] = quality_provider
    embedding_provider = (
        OpenAICompatibleEmbeddingProvider(
            provider_name=settings.embedding_provider_name,
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            model_name=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            send_dimensions=settings.embedding_send_dimensions,
            batch_size=settings.embedding_batch_size,
            timeout_seconds=settings.embedding_timeout_seconds,
            max_retries=settings.embedding_max_retries,
        )
        if settings.embedding_api_key.get_secret_value()
        else UnconfiguredEmbeddingProvider()
    )
    context["embedding_provider"] = embedding_provider
    context["indexing_worker"] = IndexingWorker(
        IndexingRepository(database),
        quality_provider,
        embedding_provider,
        rule_config=RuleConfig(
            min_characters=settings.quality_rule_min_characters,
            max_characters=settings.quality_rule_max_characters,
            abnormal_character_ratio=settings.quality_rule_abnormal_character_ratio,
        ),
    )


async def worker_shutdown(context: dict[str, Any]) -> None:
    database = cast(Database | None, context.get("database"))
    quality_provider = context.get("quality_provider")
    embedding_provider = context.get("embedding_provider")
    try:
        close_quality_provider = getattr(quality_provider, "close", None)
        if close_quality_provider is not None:
            await close_quality_provider()
    finally:
        try:
            close_embedding_provider = getattr(embedding_provider, "close", None)
            if close_embedding_provider is not None:
                await close_embedding_provider()
        finally:
            if database is not None:
                await database.close()


async def process_document_version_job(context: dict[str, Any], job_id: str) -> None:
    runner = cast(IngestionWorker, context["ingestion_worker"])
    try:
        await runner.run(UUID(job_id))
    except Exception as error:
        logger.error(
            "Document ingestion job failed",
            extra={"job_id": job_id, "error_type": type(error).__name__},
        )
        raise


async def index_knowledge_version_job(context: dict[str, Any], job_id: str) -> None:
    runner = cast(IndexingWorker, context["indexing_worker"])
    try:
        await runner.run(UUID(job_id))
    except Exception as error:
        logger.error(
            "Knowledge indexing job failed",
            extra={"job_id": job_id, "error_type": type(error).__name__},
        )
        raise


_settings = Settings()
_redis_settings = RedisSettings.from_dsn(_settings.redis_url.get_secret_value())
_redis_settings.conn_timeout = max(1, math.ceil(_settings.dependency_timeout_seconds))
_redis_settings.conn_retries = 0


class WorkerSettings:
    functions = [
        func(
            process_document_version_job,
            name="process_document_version_job",
            keep_result=0,
            max_tries=1,
            timeout=300,
        ),
        func(
            index_knowledge_version_job,
            name="index_knowledge_version_job",
            keep_result=0,
            max_tries=1,
            timeout=300,
        ),
    ]
    on_startup = worker_startup
    on_shutdown = worker_shutdown
    redis_settings = _redis_settings
    queue_name = INGESTION_QUEUE_NAME
    max_jobs = 2
    job_timeout = 300
    job_completion_wait = 30
    retry_jobs = False
    health_check_key = f"{INGESTION_QUEUE_NAME}:health"
    job_serializer = json_serializer
    job_deserializer = json_deserializer
    log_results = False
