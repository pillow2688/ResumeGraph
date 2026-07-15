import asyncio
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import SecretStr

from app.quality.prompt import (
    QualityPromptChunk,
    build_quality_messages,
    prepare_quality_prompt_chunks,
)
from app.quality.rules import ChunkRuleResult
from app.schemas.indexing import (
    ChunkQualityDecision,
    QualityResponseValidationError,
    validate_quality_batch,
)


class QualityProviderError(RuntimeError):
    """A sanitized external quality-provider failure safe for service translation."""


class QualityProviderNotConfiguredError(QualityProviderError):
    def __init__(self) -> None:
        super().__init__("The quality provider API key is not configured.")


class UnconfiguredQualityProvider:
    model_name = "unconfigured"

    async def evaluate(
        self,
        rule_results: list[ChunkRuleResult],
    ) -> list[ChunkQualityDecision]:
        del rule_results
        raise QualityProviderNotConfiguredError


class DeepSeekQualityProvider:
    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        batch_size: int = 5,
        thinking_enabled: bool = False,
        client: Any | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Quality provider timeout must be positive.")
        if max_retries < 0:
            raise ValueError("Quality provider retries cannot be negative.")
        if not 0 < batch_size <= 20:
            raise ValueError("Quality provider batch size must be within 1..20.")
        if client is None and not api_key.get_secret_value():
            raise ValueError("Quality provider API key is not configured.")

        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._batch_size = batch_size
        self._thinking_enabled = thinking_enabled
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
            f"{type(self).__name__}(model={self._model!r}, "
            f"thinking_enabled={self._thinking_enabled!r})"
        )

    @property
    def model_name(self) -> str:
        return self._model

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()

    async def evaluate(
        self,
        rule_results: list[ChunkRuleResult],
    ) -> list[ChunkQualityDecision]:
        chunks = prepare_quality_prompt_chunks(rule_results)
        if not chunks:
            return []

        decisions: list[ChunkQualityDecision] = []
        for offset in range(0, len(chunks), self._batch_size):
            decisions.extend(await self._evaluate_batch(chunks[offset : offset + self._batch_size]))
        return decisions

    async def _evaluate_batch(
        self,
        chunks: list[QualityPromptChunk],
    ) -> list[ChunkQualityDecision]:
        expected_chunk_ids = {chunk.chunk_id for chunk in chunks}
        messages = build_quality_messages(chunks)
        for attempt in range(self._max_retries + 1):
            try:
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=self._model,
                        messages=messages,
                        temperature=0,
                        response_format={"type": "json_object"},
                        extra_body={
                            "thinking": {
                                "type": ("enabled" if self._thinking_enabled else "disabled")
                            }
                        },
                    ),
                    timeout=self._timeout_seconds,
                )
                try:
                    content = response.choices[0].message.content
                except (AttributeError, IndexError, TypeError):
                    raise QualityResponseValidationError(
                        "Malformed quality response envelope."
                    ) from None
                if not isinstance(content, str) or not content.strip():
                    raise QualityResponseValidationError("Empty quality response.")
                return validate_quality_batch(
                    content,
                    expected_chunk_ids=expected_chunk_ids,
                )
            except QualityResponseValidationError:
                if attempt < self._max_retries:
                    continue
                raise QualityProviderError(
                    "Quality provider returned an invalid response."
                ) from None
            except TimeoutError:
                if attempt < self._max_retries:
                    continue
                raise QualityProviderError("Quality provider is temporarily unavailable.") from None
            except (APIConnectionError, APIStatusError, APITimeoutError, RuntimeError) as exc:
                if self._is_retryable(exc) and attempt < self._max_retries:
                    continue
                if self._is_retryable(exc):
                    message = "Quality provider is temporarily unavailable."
                else:
                    message = "Quality provider request was rejected."
                raise QualityProviderError(message) from None

        raise AssertionError("Unreachable quality-provider retry state.")

    @staticmethod
    def _is_retryable(exc: BaseException) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            return True
        return status_code in {408, 409, 429} or status_code >= 500
