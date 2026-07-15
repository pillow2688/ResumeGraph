import asyncio
from typing import Any, Literal, Protocol, runtime_checkable

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import SecretStr

ChatErrorCode = Literal[
    "chat_provider_unavailable",
    "chat_provider_auth_failed",
    "chat_provider_rate_limited",
    "chat_provider_invalid_response",
    "chat_timeout",
]


class ChatProviderError(RuntimeError):
    """Supplier-neutral Chat failure safe for API translation and logs."""

    def __init__(self, code: ChatErrorCode) -> None:
        self.code = code
        super().__init__(code)


class ChatProviderNotConfiguredError(ChatProviderError):
    def __init__(self) -> None:
        super().__init__("chat_provider_unavailable")


@runtime_checkable
class ChatProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str: ...


class OpenAICompatibleChatProvider:
    """Shared-client adapter for a bounded OpenAI-compatible JSON completion."""

    def __init__(
        self,
        *,
        provider_name: str,
        api_key: SecretStr,
        base_url: str,
        model_name: str,
        timeout_seconds: float,
        client: Any | None = None,
    ) -> None:
        if not provider_name.strip():
            raise ValueError("Chat provider name cannot be empty.")
        if not base_url.strip():
            raise ValueError("Chat base URL cannot be empty.")
        if not model_name.strip():
            raise ValueError("Chat model name cannot be empty.")
        if timeout_seconds <= 0:
            raise ValueError("Chat timeout must be positive.")
        if client is None and not api_key.get_secret_value():
            raise ValueError("Chat API key is not configured.")

        self._provider_name = provider_name
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds
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
            f"model_name={self._model_name!r})"
        )

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        try:
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0,
                    response_format={"type": "json_object"},
                    extra_body={"thinking": {"type": "disabled"}},
                ),
                timeout=self._timeout_seconds,
            )
            try:
                content = response.choices[0].message.content
            except (AttributeError, IndexError, TypeError):
                raise ChatProviderError("chat_provider_invalid_response") from None
            if not isinstance(content, str) or not content.strip():
                raise ChatProviderError("chat_provider_invalid_response")
            return content
        except ChatProviderError:
            raise
        except (TimeoutError, APITimeoutError):
            raise ChatProviderError("chat_timeout") from None
        except (APIConnectionError, APIStatusError, RuntimeError) as error:
            raise ChatProviderError(self._classify_supplier_error(error)) from None

    @staticmethod
    def _classify_supplier_error(error: BaseException) -> ChatErrorCode:
        status_code = getattr(error, "status_code", None)
        if status_code in {401, 403}:
            return "chat_provider_auth_failed"
        if status_code == 429:
            return "chat_provider_rate_limited"
        if status_code == 408:
            return "chat_timeout"
        if status_code is None or status_code in {409}:
            return "chat_provider_unavailable"
        if isinstance(status_code, int) and status_code >= 500:
            return "chat_provider_unavailable"
        return "chat_provider_invalid_response"


class UnconfiguredChatProvider:
    """Production-safe placeholder that never falls back to fabricated answers."""

    def __init__(
        self,
        *,
        provider_name: str = "unconfigured",
        model_name: str = "unconfigured",
    ) -> None:
        if not provider_name.strip() or not model_name.strip():
            raise ValueError("The unavailable Chat identity is invalid.")
        self.provider_name = provider_name
        self.model_name = model_name

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        raise ChatProviderNotConfiguredError
