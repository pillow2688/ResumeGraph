import asyncio
import math
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

import app.infrastructure.embedding as embedding_module
from app.infrastructure.embedding import (
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingProviderNotConfiguredError,
    FakeEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    UnconfiguredEmbeddingProvider,
)


def response(vectors: list[list[float]], *, indexes: list[int] | None = None):
    actual_indexes = indexes or list(range(len(vectors)))
    return SimpleNamespace(
        data=[
            SimpleNamespace(index=index, embedding=vector)
            for index, vector in zip(actual_indexes, vectors, strict=True)
        ]
    )


class FakeEmbeddings:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome == "hang":
            await asyncio.Event().wait()
        return outcome


class FakeClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.embeddings = FakeEmbeddings(outcomes)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeStatusError(RuntimeError):
    def __init__(self, status_code: int, detail: str = "supplier-secret-detail") -> None:
        self.status_code = status_code
        super().__init__(detail)


def make_provider(client: FakeClient, **overrides: object) -> OpenAICompatibleEmbeddingProvider:
    options: dict[str, object] = {
        "provider_name": "test-provider",
        "api_key": SecretStr("fictional-embedding-key"),
        "base_url": "https://embedding.example/v1",
        "model_name": "embedding-test",
        "dimensions": 3,
        "send_dimensions": True,
        "batch_size": 2,
        "timeout_seconds": 0.02,
        "max_retries": 2,
        "client": client,
    }
    options.update(overrides)
    return OpenAICompatibleEmbeddingProvider(**options)


def test_fake_provider_is_deterministic_dimensioned_and_satisfies_protocol() -> None:
    provider = FakeEmbeddingProvider(
        provider_name="fake",
        model_name="fake-test",
        dimensions=4,
    )

    first = asyncio.run(provider.embed_texts(["alpha", "beta", "alpha"]))
    second = asyncio.run(provider.embed_texts(["alpha"]))

    assert isinstance(provider, EmbeddingProvider)
    assert provider.provider_name == "fake"
    assert provider.model_name == "fake-test"
    assert all(len(vector) == 4 for vector in first)
    assert first[0] == first[2] == second[0]
    assert first[0] != first[1]
    assert all(math.isfinite(value) for vector in first for value in vector)


def test_provider_creates_one_shared_client_with_custom_base_url_and_closes_it(
    monkeypatch,
) -> None:
    client = FakeClient([])
    captured: dict[str, object] = {}

    def build_client(**kwargs: object) -> FakeClient:
        captured.update(kwargs)
        return client

    monkeypatch.setattr(embedding_module, "AsyncOpenAI", build_client)
    provider = OpenAICompatibleEmbeddingProvider(
        provider_name="custom",
        api_key=SecretStr("fictional-embedding-key"),
        base_url="https://custom.example/openai/v1",
        model_name="embedding-custom",
        dimensions=3,
        send_dimensions=True,
        batch_size=10,
        timeout_seconds=30,
        max_retries=2,
    )

    asyncio.run(provider.close())

    assert captured["base_url"] == "https://custom.example/openai/v1"
    assert captured["api_key"] == "fictional-embedding-key"
    assert captured["max_retries"] == 0
    assert client.closed is True
    assert "fictional-embedding-key" not in repr(provider)


@pytest.mark.parametrize("send_dimensions", [True, False])
def test_dimensions_parameter_can_be_enabled_or_omitted(send_dimensions: bool) -> None:
    client = FakeClient([response([[0.1, 0.2, 0.3]])])
    provider = make_provider(
        client,
        send_dimensions=send_dimensions,
        max_retries=0,
    )

    vectors = asyncio.run(provider.embed_texts(["safe text"]))

    assert vectors == [[0.1, 0.2, 0.3]]
    request = client.embeddings.calls[0]
    assert request["model"] == "embedding-test"
    assert request["input"] == ["safe text"]
    assert ("dimensions" in request) is send_dimensions
    if send_dimensions:
        assert request["dimensions"] == 3


def test_provider_batches_requests_and_restores_response_index_order() -> None:
    client = FakeClient(
        [
            response(
                [[2.0, 2.0, 2.0], [1.0, 1.0, 1.0]],
                indexes=[1, 0],
            ),
            response([[3.0, 3.0, 3.0]]),
        ]
    )
    provider = make_provider(client, batch_size=2, max_retries=0)

    vectors = asyncio.run(provider.embed_texts(["first", "second", "third"]))

    assert vectors == [
        [1.0, 1.0, 1.0],
        [2.0, 2.0, 2.0],
        [3.0, 3.0, 3.0],
    ]
    assert [call["input"] for call in client.embeddings.calls] == [
        ["first", "second"],
        ["third"],
    ]


@pytest.mark.parametrize(
    ("outcome", "expected_code"),
    [
        (response([]), "embedding_provider_invalid_response"),
        (response([[0.1, 0.2]]), "embedding_dimension_mismatch"),
        (response([[0.1, float("nan"), 0.3]]), "embedding_provider_invalid_response"),
        (response([[0.1, float("inf"), 0.3]]), "embedding_provider_invalid_response"),
        (response([[0.1, 0.2, 0.3]], indexes=[1]), "embedding_provider_invalid_response"),
    ],
)
def test_invalid_count_indexes_dimensions_and_values_use_stable_error_codes(
    outcome: object,
    expected_code: str,
) -> None:
    provider = make_provider(FakeClient([outcome]), max_retries=0)

    with pytest.raises(EmbeddingProviderError) as raised:
        asyncio.run(provider.embed_texts(["must not appear in the error"]))

    assert raised.value.code == expected_code
    assert str(raised.value) == expected_code
    assert "must not appear" not in str(raised.value)


def test_auth_failure_is_not_retried_and_does_not_leak_supplier_details_or_key() -> None:
    client = FakeClient([FakeStatusError(401)])
    provider = make_provider(client)

    with pytest.raises(EmbeddingProviderError) as raised:
        asyncio.run(provider.embed_texts(["safe text"]))

    assert raised.value.code == "embedding_provider_auth_failed"
    assert len(client.embeddings.calls) == 1
    assert "supplier-secret-detail" not in str(raised.value)
    assert "fictional-embedding-key" not in str(raised.value)
    assert "fictional-embedding-key" not in repr(provider)


@pytest.mark.parametrize(
    ("outcomes", "expected_code"),
    [
        ([FakeStatusError(429)] * 3, "embedding_provider_rate_limited"),
        ([FakeStatusError(503)] * 3, "embedding_provider_unavailable"),
        (["hang"] * 3, "embedding_timeout"),
    ],
)
def test_rate_limit_timeout_and_server_failure_have_a_finite_retry_budget(
    outcomes: list[object],
    expected_code: str,
) -> None:
    client = FakeClient(outcomes)
    provider = make_provider(client, max_retries=2)

    with pytest.raises(EmbeddingProviderError) as raised:
        asyncio.run(provider.embed_texts(["safe text"]))

    assert raised.value.code == expected_code
    assert len(client.embeddings.calls) == 3


def test_unconfigured_provider_fails_explicitly_and_is_never_a_fake() -> None:
    provider = UnconfiguredEmbeddingProvider()

    with pytest.raises(EmbeddingProviderNotConfiguredError) as raised:
        asyncio.run(provider.embed_texts(["must not leave the process"]))

    assert raised.value.code == "embedding_provider_unavailable"
    assert provider.provider_name == "unconfigured"
    assert provider.model_name == "unconfigured"
    assert provider.dimensions == 0
