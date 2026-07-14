import asyncio
import importlib
import importlib.util
import json
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest


def load_module(name: str):
    assert importlib.util.find_spec(name) is not None, f"{name} must exist"
    return importlib.import_module(name)


def run[T](awaitable: Awaitable[T]) -> T:
    return asyncio.run(awaitable)


class FakeRedisOperations:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.increment_calls: list[tuple[str, int]] = []

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None:
        self.values[key] = value
        self.ttls[key] = ttl_seconds

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.ttls.pop(key, None)

    async def increment_with_ttl(self, key: str, ttl_seconds: int) -> int:
        self.increment_calls.append((key, ttl_seconds))
        count = int(self.values.get(key, "0")) + 1
        self.values[key] = str(count)
        self.ttls.setdefault(key, ttl_seconds)
        return count


def test_recruiter_session_uses_separate_digest_key_and_minimal_payload() -> None:
    session_module = load_module("app.infrastructure.recruiter_session")
    redis = FakeRedisOperations()
    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    store = session_module.RecruiterSessionStore(redis, clock=lambda: now)
    raw_token = "raw-recruiter-session-token"
    grant_id = uuid4()
    project_ids = [uuid4(), uuid4()]

    session = run(
        store.create(
            session_token=raw_token,
            grant_id=grant_id,
            allowed_project_ids_snapshot=project_ids,
            ttl_seconds=1800,
            expires_at_limit=now + timedelta(hours=1),
        )
    )

    key = next(iter(redis.values))
    payload = json.loads(redis.values[key])
    assert key.startswith("recruiter_session:")
    assert not key.startswith("admin_session:")
    assert raw_token not in key
    assert raw_token not in redis.values[key]
    assert redis.ttls[key] == 1800
    assert session.grant_id == grant_id
    assert session.expires_at == now + timedelta(seconds=1800)
    assert set(payload) == {
        "grant_id",
        "created_at",
        "expires_at",
        "allowed_project_ids_snapshot",
    }
    assert payload["allowed_project_ids_snapshot"] == [str(value) for value in project_ids]


def test_recruiter_session_read_delete_expiry_and_malformed_timestamp() -> None:
    session_module = load_module("app.infrastructure.recruiter_session")
    redis = FakeRedisOperations()
    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    store = session_module.RecruiterSessionStore(redis, clock=lambda: now)
    token = "opaque-token"
    created = run(
        store.create(
            session_token=token,
            grant_id=uuid4(),
            allowed_project_ids_snapshot=[uuid4()],
            ttl_seconds=60,
            expires_at_limit=now + timedelta(minutes=5),
        )
    )

    assert run(store.read(token)) == created
    store._clock = lambda: now + timedelta(seconds=61)
    assert run(store.read(token)) is None

    malformed_token = "malformed-token"
    redis.values[store._key(malformed_token)] = json.dumps(
        {
            "grant_id": str(uuid4()),
            "created_at": "2026-07-14T10:00:00",
            "expires_at": "2026-07-14T11:00:00",
            "allowed_project_ids_snapshot": [str(uuid4())],
        }
    )
    assert run(store.read(malformed_token)) is None

    run(store.delete(token))
    assert store._key(token) not in redis.values


def test_recruiter_session_ttl_uses_write_time_and_never_exceeds_grant_expiry() -> None:
    session_module = load_module("app.infrastructure.recruiter_session")
    redis = FakeRedisOperations()
    grant_checked_at = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    write_time = grant_checked_at + timedelta(seconds=5)
    grant_expires_at = grant_checked_at + timedelta(seconds=60)
    store = session_module.RecruiterSessionStore(redis, clock=lambda: write_time)

    session = run(
        store.create(
            session_token="opaque-token",
            grant_id=uuid4(),
            allowed_project_ids_snapshot=[uuid4()],
            ttl_seconds=1800,
            expires_at_limit=grant_expires_at,
        )
    )

    assert next(iter(redis.ttls.values())) == 55
    assert session.expires_at == grant_expires_at

    with pytest.raises(session_module.RecruiterSessionLifetimeError):
        run(
            store.create(
                session_token="expired-grant-token",
                grant_id=uuid4(),
                allowed_project_ids_snapshot=[uuid4()],
                ttl_seconds=1800,
                expires_at_limit=write_time,
            )
        )


def test_generic_failure_limiter_hashes_identifier_and_uses_atomic_ttl() -> None:
    limiter_module = load_module("app.infrastructure.failure_limiter")
    redis = FakeRedisOperations()
    limiter = limiter_module.FailureRateLimiter(
        redis,
        key_prefix="access_exchange_failures",
        max_failures=2,
        window_seconds=600,
    )
    client_host = "127.0.0.1"

    assert run(limiter.is_limited(client_host)) is False
    assert run(limiter.record_failure(client_host)) == 1
    assert run(limiter.record_failure(client_host)) == 2
    assert run(limiter.is_limited(client_host)) is True

    key, ttl = redis.increment_calls[0]
    assert key.startswith("access_exchange_failures:")
    assert client_host not in key
    assert ttl == 600
    assert redis.ttls[key] == 600

    run(limiter.clear(client_host))
    assert run(limiter.is_limited(client_host)) is False


def test_generic_failure_limiter_fails_closed_on_malformed_counter() -> None:
    limiter_module = load_module("app.infrastructure.failure_limiter")
    redis = FakeRedisOperations()
    limiter = limiter_module.FailureRateLimiter(
        redis,
        key_prefix="access_exchange_failures",
        max_failures=10,
        window_seconds=600,
    )
    redis.values[limiter._key("127.0.0.1")] = "not-an-integer"

    assert run(limiter.is_limited("127.0.0.1")) is True
