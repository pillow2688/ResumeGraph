import logging
import math
from typing import Any, cast
from uuid import UUID

from arq.connections import RedisSettings
from arq.worker import func

from app.core.config import Settings
from app.infrastructure.database import Database
from app.infrastructure.job_queue import (
    INGESTION_QUEUE_NAME,
    json_deserializer,
    json_serializer,
)
from app.repositories.ingestion import IngestionRepository
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


async def worker_shutdown(context: dict[str, Any]) -> None:
    database = cast(Database | None, context.get("database"))
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
        )
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
