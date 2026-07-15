import asyncio
import json
from dataclasses import dataclass
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

import app.infrastructure.deepseek_quality as deepseek_quality_module
from app.infrastructure.deepseek_quality import (
    DeepSeekQualityProvider,
    QualityProviderError,
)
from app.quality.rules import ChunkRuleInput, RuleConfig, validate_chunks


def make_rule_result(content: str, *, chunk_id: UUID | None = None):
    actual_id = chunk_id or uuid4()
    return validate_chunks(
        [
            ChunkRuleInput(
                chunk_id=actual_id,
                chunk_index=0,
                content=content,
                content_hash=sha256(content.encode()).hexdigest(),
            )
        ],
        config=RuleConfig(min_characters=0),
    )[0]


def response_json(chunk_ids: list[UUID]) -> str:
    return json.dumps(
        {
            "results": [
                {
                    "chunk_id": str(chunk_id),
                    "is_indexable": True,
                    "issues": [],
                    "knowledge_type": "technical_decision",
                    "topics": ["RAG"],
                    "technologies": ["FastAPI"],
                    "reason": "包含明确的技术决策",
                }
                for chunk_id in chunk_ids
            ]
        }
    )


@dataclass
class FakeMessage:
    content: str | None
    reasoning_content: str = "private chain of thought that must be ignored"


class FakeCompletions:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome == "hang":
            await asyncio.Event().wait()
        if outcome == "empty_choices":
            return SimpleNamespace(choices=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=FakeMessage(content=str(outcome)))])


class FakeClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(outcomes))
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeStatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"provider status {status_code}")


def make_provider(client: FakeClient, **overrides: object) -> DeepSeekQualityProvider:
    options: dict[str, object] = {
        "api_key": SecretStr("fictional-provider-key"),
        "base_url": "https://api.deepseek.example",
        "model": "deepseek-v4-pro",
        "timeout_seconds": 0.05,
        "max_retries": 2,
        "client": client,
    }
    options.update(overrides)
    return DeepSeekQualityProvider(**options)


def test_provider_uses_json_output_temperature_zero_and_disables_thinking() -> None:
    chunk = make_rule_result("Use PostgreSQL as the authorization source of truth.")
    client = FakeClient([response_json([chunk.chunk_id])])
    provider = make_provider(client)

    result = asyncio.run(provider.evaluate([chunk]))

    assert result[0].chunk_id == chunk.chunk_id
    request = client.chat.completions.calls[0]
    assert request["model"] == "deepseek-v4-pro"
    assert request["temperature"] == 0
    assert request["response_format"] == {"type": "json_object"}
    assert request["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "private chain of thought" not in repr(result)


def test_hard_secrets_are_not_sent_and_pii_is_redacted_before_external_call() -> None:
    secret = "api_key = sk-fictional1234567890abcdef"
    pii = "Contact fictional.person@example.test or 13800138000 for implementation details."
    secret_chunk = make_rule_result(secret)
    pii_chunk = make_rule_result(pii)
    clean_chunk = make_rule_result("The service uses bounded retries and explicit timeouts.")
    client = FakeClient([response_json([pii_chunk.chunk_id, clean_chunk.chunk_id])])
    provider = make_provider(client)

    decisions = asyncio.run(provider.evaluate([secret_chunk, pii_chunk, clean_chunk]))

    assert {item.chunk_id for item in decisions} == {
        pii_chunk.chunk_id,
        clean_chunk.chunk_id,
    }
    serialized_request = json.dumps(
        client.chat.completions.calls[0], ensure_ascii=False, default=str
    )
    assert secret not in serialized_request
    assert "fictional.person@example.test" not in serialized_request
    assert "13800138000" not in serialized_request
    assert "[REDACTED_EMAIL]" in serialized_request
    assert "[REDACTED_PHONE]" in serialized_request


def test_all_hard_blocked_chunks_skip_the_provider_entirely() -> None:
    client = FakeClient([])
    provider = make_provider(client)

    result = asyncio.run(
        provider.evaluate([make_rule_result("password = fictional-password-value")])
    )

    assert result == []
    assert client.chat.completions.calls == []


def test_provider_uses_configured_finite_batches_and_validates_each_batch() -> None:
    chunks = [
        make_rule_result(f"Clean technical chunk {index} with deterministic content.")
        for index in range(3)
    ]
    client = FakeClient(
        [
            response_json([chunks[0].chunk_id, chunks[1].chunk_id]),
            response_json([chunks[2].chunk_id]),
        ]
    )
    provider = make_provider(client, batch_size=2)

    results = asyncio.run(provider.evaluate(chunks))

    assert [result.chunk_id for result in results] == [chunk.chunk_id for chunk in chunks]
    assert len(client.chat.completions.calls) == 2
    first_payload = client.chat.completions.calls[0]["messages"][1]["content"]
    second_payload = client.chat.completions.calls[1]["messages"][1]["content"]
    assert str(chunks[2].chunk_id) not in first_payload
    assert str(chunks[2].chunk_id) in second_payload


def test_invalid_json_is_retried_but_batch_id_mismatch_is_never_accepted() -> None:
    chunk = make_rule_result("A deterministic chunk used by the unit test.")
    client = FakeClient(["not-json", response_json([chunk.chunk_id])])
    provider = make_provider(client)

    result = asyncio.run(provider.evaluate([chunk]))

    assert result[0].chunk_id == chunk.chunk_id
    assert len(client.chat.completions.calls) == 2

    mismatched = FakeClient([response_json([uuid4()])])
    with pytest.raises(QualityProviderError, match="invalid response"):
        asyncio.run(make_provider(mismatched, max_retries=0).evaluate([chunk]))


def test_empty_provider_envelope_is_treated_as_invalid_and_retried() -> None:
    chunk = make_rule_result("A deterministic chunk used by the unit test.")
    client = FakeClient(["empty_choices", response_json([chunk.chunk_id])])

    result = asyncio.run(make_provider(client).evaluate([chunk]))

    assert result[0].chunk_id == chunk.chunk_id
    assert len(client.chat.completions.calls) == 2


def test_provider_does_not_close_an_injected_client_it_does_not_own() -> None:
    client = FakeClient([])
    provider = make_provider(client)

    asyncio.run(provider.close())

    assert client.closed is False


def test_provider_closes_the_async_client_it_creates(monkeypatch) -> None:
    client = FakeClient([])
    monkeypatch.setattr(
        deepseek_quality_module,
        "AsyncOpenAI",
        lambda **_kwargs: client,
    )
    provider = DeepSeekQualityProvider(
        api_key=SecretStr("fictional-provider-key"),
        base_url="https://api.deepseek.example",
        model="deepseek-v4-pro",
        timeout_seconds=1,
        max_retries=0,
    )

    asyncio.run(provider.close())

    assert client.closed is True


def test_timeout_and_retryable_statuses_have_a_finite_retry_budget() -> None:
    chunk = make_rule_result("A deterministic chunk used by the unit test.")
    timeout_client = FakeClient(["hang", "hang", "hang"])

    with pytest.raises(QualityProviderError, match="temporarily unavailable"):
        asyncio.run(make_provider(timeout_client).evaluate([chunk]))
    assert len(timeout_client.chat.completions.calls) == 3

    retry_client = FakeClient([FakeStatusError(429), response_json([chunk.chunk_id])])
    result = asyncio.run(make_provider(retry_client).evaluate([chunk]))
    assert result[0].chunk_id == chunk.chunk_id
    assert len(retry_client.chat.completions.calls) == 2


@pytest.mark.parametrize("status_code", [401, 402])
def test_non_retryable_auth_or_payment_errors_fail_once_without_leaking_details(
    status_code: int,
) -> None:
    chunk = make_rule_result("A deterministic chunk used by the unit test.")
    client = FakeClient([FakeStatusError(status_code)])

    with pytest.raises(QualityProviderError) as raised:
        asyncio.run(make_provider(client).evaluate([chunk]))

    assert len(client.chat.completions.calls) == 1
    assert str(status_code) not in str(raised.value)
    assert "fictional-provider-key" not in str(raised.value)
    assert "fictional-provider-key" not in repr(make_provider(FakeClient([])))
