import asyncio
from uuid import UUID, uuid4

from pydantic import SecretStr

from app.core.config import Settings
from app.infrastructure.embedding import (
    FakeEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    UnconfiguredEmbeddingProvider,
)
from app.infrastructure.job_queue import INGESTION_QUEUE_NAME
from app.worker import (
    WorkerSettings,
    index_knowledge_version_job,
    process_document_version_job,
    worker_shutdown,
    worker_startup,
)


class FakeRunner:
    def __init__(self) -> None:
        self.job_ids: list[UUID] = []

    async def run(self, job_id: UUID) -> None:
        self.job_ids.append(job_id)


class FakeClosableProvider:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_worker_settings_register_two_bounded_functions_on_the_same_queue() -> None:
    assert WorkerSettings.queue_name == INGESTION_QUEUE_NAME
    assert WorkerSettings.max_jobs == 2
    assert WorkerSettings.job_timeout == 300
    assert WorkerSettings.log_results is False
    assert len(WorkerSettings.functions) == 2
    functions = {function.name: function for function in WorkerSettings.functions}
    assert set(functions) == {
        "process_document_version_job",
        "index_knowledge_version_job",
    }
    assert all(function.max_tries == 1 for function in functions.values())
    assert all(function.keep_result_s == 0 for function in functions.values())


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


def test_indexing_worker_entrypoint_uses_the_same_postgresql_job_uuid_boundary() -> None:
    runner = FakeRunner()
    job_id = uuid4()

    asyncio.run(
        index_knowledge_version_job(
            {"indexing_worker": runner},
            str(job_id),
        )
    )

    assert runner.job_ids == [job_id]


def test_worker_startup_and_shutdown_own_database_lifespan() -> None:
    async def exercise() -> None:
        settings = Settings(
            deepseek_api_key=SecretStr(""),
            embedding_api_key=SecretStr(""),
            _env_file=None,
        )
        context: dict[str, object] = {"settings": settings}
        await worker_startup(context)
        assert "database" in context
        assert "ingestion_worker" in context
        assert "indexing_worker" in context
        assert isinstance(context["embedding_provider"], UnconfiguredEmbeddingProvider)
        assert not isinstance(context["embedding_provider"], FakeEmbeddingProvider)
        await worker_shutdown(context)

    asyncio.run(exercise())


def test_worker_shutdown_closes_the_owned_quality_provider() -> None:
    async def exercise() -> None:
        provider = FakeClosableProvider()
        await worker_shutdown({"quality_provider": provider})
        assert provider.closed is True

    asyncio.run(exercise())


def test_worker_builds_one_generic_openai_compatible_embedding_provider() -> None:
    async def exercise() -> None:
        settings = Settings(
            embedding_api_key=SecretStr("fictional-worker-embedding-key"),
            _env_file=None,
        )
        context: dict[str, object] = {"settings": settings}

        await worker_startup(context)

        provider = context["embedding_provider"]
        assert isinstance(provider, OpenAICompatibleEmbeddingProvider)
        assert provider.provider_name == "zhipu"
        assert provider.model_name == "embedding-3"
        assert provider.dimensions == 1024
        assert not isinstance(provider, FakeEmbeddingProvider)
        await worker_shutdown(context)

    asyncio.run(exercise())
