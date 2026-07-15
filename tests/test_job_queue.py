import asyncio
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from app.infrastructure.job_queue import (
    INGESTION_QUEUE_NAME,
    ArqJobQueue,
    json_deserializer,
    json_serializer,
)
from app.services.ingestion import QueueUnavailableError


class FakePool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self.closed = False

    async def enqueue_job(self, function: str, *args: object, **kwargs: object) -> object:
        self.calls.append((function, args, kwargs))
        return object()

    async def aclose(self, *, close_connection_pool: bool) -> None:
        assert close_connection_pool is True
        self.closed = True


def test_json_job_serializer_round_trips_only_data() -> None:
    payload = {
        "f": "process_document_version_job",
        "a": ("fictional-job-id",),
        "k": {},
        "t": 1,
    }

    restored = json_deserializer(json_serializer(payload))

    assert restored == {**payload, "a": ["fictional-job-id"]}


def test_arq_queue_uses_postgresql_job_uuid_for_payload_and_uniqueness() -> None:
    pool = FakePool()
    factory_calls: list[object] = []

    async def pool_factory(*args: object, **kwargs: object) -> FakePool:
        factory_calls.append((args, kwargs))
        return pool

    queue = ArqJobQueue(
        "redis://redis:6379/0",
        timeout_seconds=3,
        pool_factory=pool_factory,
    )
    job_id = uuid4()

    asyncio.run(queue.enqueue(job_id))
    asyncio.run(queue.enqueue(job_id))
    asyncio.run(queue.close())

    assert len(factory_calls) == 1
    assert pool.calls == [
        (
            "process_document_version_job",
            (str(job_id),),
            {
                "_job_id": str(job_id),
                "_queue_name": INGESTION_QUEUE_NAME,
                "_expires": 24 * 60 * 60,
            },
        ),
        (
            "process_document_version_job",
            (str(job_id),),
            {
                "_job_id": str(job_id),
                "_queue_name": INGESTION_QUEUE_NAME,
                "_expires": 24 * 60 * 60,
            },
        ),
    ]
    assert pool.closed is True


def test_indexing_reuses_the_same_arq_queue_with_a_distinct_worker_function() -> None:
    pool = FakePool()

    async def pool_factory(*_args: object, **_kwargs: object) -> FakePool:
        return pool

    queue = ArqJobQueue(
        "redis://redis:6379/0",
        timeout_seconds=3,
        pool_factory=pool_factory,
    )
    job_id = uuid4()

    asyncio.run(queue.enqueue_indexing(job_id))

    assert pool.calls == [
        (
            "index_knowledge_version_job",
            (str(job_id),),
            {
                "_job_id": str(job_id),
                "_queue_name": INGESTION_QUEUE_NAME,
                "_expires": 24 * 60 * 60,
            },
        )
    ]


def test_arq_queue_sanitizes_redis_failures() -> None:
    async def failing_factory(*_args: object, **_kwargs: object):
        raise RedisError("redis://user:secret@redis:6379/0")

    queue = ArqJobQueue(
        "redis://redis:6379/0",
        timeout_seconds=1,
        pool_factory=failing_factory,
    )

    with pytest.raises(QueueUnavailableError) as raised:
        asyncio.run(queue.enqueue(uuid4()))

    assert "secret" not in str(raised.value).lower()
    assert "redis://" not in str(raised.value).lower()
