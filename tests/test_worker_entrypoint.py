import asyncio
from uuid import UUID, uuid4

from app.infrastructure.job_queue import INGESTION_QUEUE_NAME
from app.worker import (
    WorkerSettings,
    process_document_version_job,
    worker_shutdown,
    worker_startup,
)


class FakeRunner:
    def __init__(self) -> None:
        self.job_ids: list[UUID] = []

    async def run(self, job_id: UUID) -> None:
        self.job_ids.append(job_id)


def test_worker_settings_register_one_bounded_ingestion_function() -> None:
    assert WorkerSettings.queue_name == INGESTION_QUEUE_NAME
    assert WorkerSettings.max_jobs == 2
    assert WorkerSettings.job_timeout == 300
    assert WorkerSettings.log_results is False
    assert len(WorkerSettings.functions) == 1
    function = WorkerSettings.functions[0]
    assert function.name == "process_document_version_job"
    assert function.max_tries == 1
    assert function.keep_result_s == 0


def test_worker_entrypoint_parses_postgresql_job_uuid_and_calls_runner() -> None:
    runner = FakeRunner()
    job_id = uuid4()

    asyncio.run(
        process_document_version_job(
            {"ingestion_worker": runner},
            str(job_id),
        )
    )

    assert runner.job_ids == [job_id]


def test_worker_startup_and_shutdown_own_database_lifespan() -> None:
    async def exercise() -> None:
        context: dict[str, object] = {}
        await worker_startup(context)
        assert "database" in context
        assert "ingestion_worker" in context
        await worker_shutdown(context)

    asyncio.run(exercise())
