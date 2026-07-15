import asyncio
import json
import math
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from arq.connections import ArqRedis, RedisSettings, create_pool
from redis.exceptions import RedisError

from app.services.ingestion import QueueUnavailableError

INGESTION_QUEUE_NAME = "resumegraph:ingestion"


def json_serializer(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def json_deserializer(value: bytes) -> dict[str, Any]:
    restored = json.loads(value.decode("utf-8"))
    if not isinstance(restored, dict):
        raise ValueError("ARQ job payload must be an object")
    return restored


class ArqJobQueue:
    def __init__(
        self,
        redis_url: str,
        *,
        timeout_seconds: float,
        pool_factory: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self._redis_settings = RedisSettings.from_dsn(redis_url)
        self._redis_settings.conn_timeout = max(1, math.ceil(timeout_seconds))
        self._redis_settings.conn_retries = 0
        self._timeout_seconds = timeout_seconds
        self._pool_factory = pool_factory or create_pool
        self._pool: ArqRedis | Any | None = None
        self._pool_lock = asyncio.Lock()

    async def _get_pool(self) -> ArqRedis | Any:
        if self._pool is not None:
            return self._pool
        async with self._pool_lock:
            if self._pool is None:
                self._pool = await self._pool_factory(
                    self._redis_settings,
                    job_serializer=json_serializer,
                    job_deserializer=json_deserializer,
                    default_queue_name=INGESTION_QUEUE_NAME,
                )
        return self._pool

    async def enqueue(self, job_id: UUID) -> None:
        try:
            pool = await asyncio.wait_for(
                self._get_pool(),
                timeout=self._timeout_seconds,
            )
            await asyncio.wait_for(
                pool.enqueue_job(
                    "process_document_version_job",
                    str(job_id),
                    _job_id=str(job_id),
                    _queue_name=INGESTION_QUEUE_NAME,
                    _expires=24 * 60 * 60,
                ),
                timeout=self._timeout_seconds,
            )
        except (RedisError, OSError, TimeoutError) as error:
            raise QueueUnavailableError from error

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose(close_connection_pool=True)
            self._pool = None
