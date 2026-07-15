import asyncio
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

import app.infrastructure.chat as chat_module
from app.infrastructure.chat import (
    ChatProvider,
    ChatProviderError,
    ChatProviderNotConfiguredError,
    OpenAICompatibleChatProvider,
    UnconfiguredChatProvider,
)


class FakeCompletions:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome == "hang":
            await asyncio.Event().wait()
        if outcome == "empty":
            return SimpleNamespace(choices=[])
        message = SimpleNamespace(
            content=outcome,
            reasoning_content="private reasoning must never be returned",
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(outcomes))
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeStatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"supplier secret status {status_code}")


def make_provider(client: FakeClient, **overrides: object) -> OpenAICompatibleChatProvider:
    options: dict[str, object] = {
        "provider_name": "deepseek",
        "api_key": SecretStr("fictional-chat-key"),
        "base_url": "https://chat.example/v1",
        "model_name": "deepseek-v4-pro",
        "timeout_seconds": 0.02,
        "client": client,
    }
    options.update(overrides)
    return OpenAICompatibleChatProvider(**options)


def test_chat_provider_requests_strict_json_and_ignores_reasoning_content() -> None:
    client = FakeClient(['{"status":"insufficient_evidence"}'])
    provider = make_provider(client)

    content = asyncio.run(
        provider.complete_json(
            system_prompt="system rules",
            user_prompt="untrusted evidence",
        )
    )

    assert isinstance(provider, ChatProvider)
    assert content == '{"status":"insufficient_evidence"}'
    request = client.chat.completions.calls[0]
    assert request["model"] == "deepseek-v4-pro"
    assert request["temperature"] == 0
    assert request["response_format"] == {"type": "json_object"}
    assert request["extra_body"] == {"thinking": {"type": "disabled"}}
    assert request["messages"] == [
        {"role": "system", "content": "system rules"},
        {"role": "user", "content": "untrusted evidence"},
    ]
    assert "private reasoning" not in content


@pytest.mark.parametrize(
    ("outcome", "expected_code"),
    [
        ("hang", "chat_timeout"),
        (FakeStatusError(401), "chat_provider_auth_failed"),
        (FakeStatusError(429), "chat_provider_rate_limited"),
        (FakeStatusError(503), "chat_provider_unavailable"),
        ("empty", "chat_provider_invalid_response"),
    ],
)
def test_chat_provider_errors_are_stable_sanitized_and_not_retried(
    outcome: object,
    expected_code: str,
) -> None:
    client = FakeClient([outcome])
    provider = make_provider(client)

    with pytest.raises(ChatProviderError) as raised:
        asyncio.run(provider.complete_json(system_prompt="safe", user_prompt="safe"))

    assert raised.value.code == expected_code
    assert str(raised.value) == expected_code
    assert len(client.chat.completions.calls) == 1
    assert "fictional-chat-key" not in repr(provider)
    assert "supplier secret" not in str(raised.value)


def test_unconfigured_chat_provider_fails_without_a_network_fallback() -> None:
    provider = UnconfiguredChatProvider(
        provider_name="deepseek",
        model_name="deepseek-v4-pro",
    )

    with pytest.raises(ChatProviderNotConfiguredError):
        asyncio.run(provider.complete_json(system_prompt="safe", user_prompt="safe"))


def test_chat_provider_closes_only_the_client_it_creates(monkeypatch) -> None:
    injected = FakeClient([])
    asyncio.run(make_provider(injected).close())
    assert injected.closed is False

    owned = FakeClient([])
    monkeypatch.setattr(chat_module, "AsyncOpenAI", lambda **_kwargs: owned)
    provider = OpenAICompatibleChatProvider(
        provider_name="deepseek",
        api_key=SecretStr("fictional-chat-key"),
        base_url="https://chat.example/v1",
        model_name="deepseek-v4-pro",
        timeout_seconds=1,
    )

    asyncio.run(provider.close())

    assert owned.closed is True
