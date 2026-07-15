import asyncio
import math
from hashlib import sha256
from typing import Any, Literal, Protocol, runtime_checkable

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import SecretStr

EmbeddingErrorCode = Literal[
    "embedding_provider_unavailable",
    "embedding_provider_auth_failed",
    "embedding_provider_rate_limited",
    "embedding_provider_invalid_response",
    "embedding_dimension_mismatch",
    "embedding_timeout",
]


class EmbeddingProviderError(RuntimeError):
    """A supplier-neutral Embedding failure safe for persistence and API translation."""

    def __init__(self, code: EmbeddingErrorCode) -> None:
        self.code = code
        super().__init__(code)


class EmbeddingProviderNotConfiguredError(EmbeddingProviderError):
    def __init__(self) -> None:
        super().__init__("embedding_provider_unavailable")


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class OpenAICompatibleEmbeddingProvider:
    """Shared-client adapter for any OpenAI-compatible Embedding endpoint."""

    def __init__(
        self,
        *,
        provider_name: str,
        api_key: SecretStr,
        base_url: str,
        model_name: str,
        dimensions: int,
        send_dimensions: bool,
        batch_size: int,
        timeout_seconds: float,
        max_retries: int,
        client: Any | None = None,
    ) -> None:
        if not provider_name.strip():
            raise ValueError("Embedding provider name cannot be empty.")
        if not base_url.strip():
            raise ValueError("Embedding base URL cannot be empty.")
        if not model_name.strip():
            raise ValueError("Embedding model name cannot be empty.")
        if dimensions <= 0:
            raise ValueError("Embedding dimensions must be positive.")
        if batch_size <= 0:
            raise ValueError("Embedding batch size must be positive.")
        if timeout_seconds <= 0:
            raise ValueError("Embedding timeout must be positive.")
        if max_retries < 0:
            raise ValueError("Embedding retries cannot be negative.")
        if client is None and not api_key.get_secret_value():
            raise ValueError("Embedding API key is not configured.")

        self._provider_name = provider_name
        self._model_name = model_name
        self._dimensions = dimensions
        self._send_dimensions = send_dimensions
        self._batch_size = batch_size
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._owns_client = client is None
        self._client = (
            AsyncOpenAI(
                api_key=api_key.get_secret_value(),
                base_url=base_url,
                timeout=timeout_seconds,
                max_retries=0,
            )
            if client is None
            else client
        )

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(provider_name={self._provider_name!r}, "
            f"model_name={self._model_name!r}, dimensions={self._dimensions!r})"
        )

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), self._batch_size):
            vectors.extend(await self._embed_batch(texts[offset : offset + self._batch_size]))
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_texts([text]))[0]

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        for attempt in range(self._max_retries + 1):
            try:
                request: dict[str, object] = {
                    "model": self._model_name,
                    "input": texts,
                }
                if self._send_dimensions:
                    request["dimensions"] = self._dimensions
                response = await asyncio.wait_for(
                    self._client.embeddings.create(**request),
                    timeout=self._timeout_seconds,
                )
                return self._validate_response(response, expected_count=len(texts))
            except EmbeddingProviderError:
                raise
            except (TimeoutError, APITimeoutError):
                if attempt < self._max_retries:
                    continue
                raise EmbeddingProviderError("embedding_timeout") from None
            except (APIConnectionError, APIStatusError, RuntimeError) as error:
                code, retryable = self._classify_supplier_error(error)
                if retryable and attempt < self._max_retries:
                    continue
                raise EmbeddingProviderError(code) from None
        raise AssertionError("Unreachable Embedding retry state.")

    def _validate_response(self, response: object, *, expected_count: int) -> list[list[float]]:
        try:
            data = response.data  # type: ignore[attr-defined]
        except AttributeError:
            raise EmbeddingProviderError("embedding_provider_invalid_response") from None
        if not isinstance(data, (list, tuple)) or len(data) != expected_count:
            raise EmbeddingProviderError("embedding_provider_invalid_response")

        by_index: dict[int, list[float]] = {}
        for item in data:
            try:
                index = item.index
                embedding = item.embedding
            except AttributeError:
                raise EmbeddingProviderError("embedding_provider_invalid_response") from None
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or index < 0
                or index >= expected_count
                or index in by_index
                or not isinstance(embedding, (list, tuple))
            ):
                raise EmbeddingProviderError("embedding_provider_invalid_response")
            if len(embedding) != self._dimensions:
                raise EmbeddingProviderError("embedding_dimension_mismatch")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in embedding
            ):
                raise EmbeddingProviderError("embedding_provider_invalid_response")
            by_index[index] = [float(value) for value in embedding]

        if set(by_index) != set(range(expected_count)):
            raise EmbeddingProviderError("embedding_provider_invalid_response")
        return [by_index[index] for index in range(expected_count)]

    @staticmethod
    def _classify_supplier_error(
        error: BaseException,
    ) -> tuple[EmbeddingErrorCode, bool]:
        status_code = getattr(error, "status_code", None)
        if status_code in {401, 403}:
            return "embedding_provider_auth_failed", False
        if status_code == 429:
            return "embedding_provider_rate_limited", True
        if status_code == 408:
            return "embedding_timeout", True
        if status_code in {409} or (isinstance(status_code, int) and status_code >= 500):
            return "embedding_provider_unavailable", True
        if status_code is None:
            return "embedding_provider_unavailable", True
        return "embedding_provider_invalid_response", False


class FakeEmbeddingProvider:
    """Deterministic, local-only Provider for tests; never a production fallback."""

    def __init__(
        self,
        *,
        provider_name: str = "fake",
        model_name: str = "fake-embedding",
        dimensions: int = 8,
    ) -> None:
        if not provider_name:
            raise ValueError("Fake Embedding provider name cannot be empty.")
        if not model_name:
            raise ValueError("Fake Embedding model name cannot be empty.")
        if dimensions <= 0:
            raise ValueError("Fake Embedding dimensions must be positive.")
        self._provider_name = provider_name
        self._model_name = model_name
        self._dimensions = dimensions

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = sha256(text.encode("utf-8")).digest()
            vectors.append(
                [(digest[index % len(digest)] / 127.5) - 1.0 for index in range(self._dimensions)]
            )
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_texts([text]))[0]


class UnconfiguredEmbeddingProvider:
    """Production-safe placeholder that prevents external or fake vectorization."""

    def __init__(
        self,
        *,
        provider_name: str = "unconfigured",
        model_name: str = "unconfigured",
        dimensions: int = 0,
    ) -> None:
        if not provider_name or not model_name or dimensions < 0:
            raise ValueError("The unavailable Embedding identity is invalid.")
        self.provider_name = provider_name
        self.model_name = model_name
        self.dimensions = dimensions

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        del texts
        raise EmbeddingProviderNotConfiguredError

    async def embed_query(self, text: str) -> list[float]:
        del text
        raise EmbeddingProviderNotConfiguredError
