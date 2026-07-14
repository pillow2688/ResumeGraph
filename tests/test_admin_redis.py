import asyncio
import importlib
import importlib.util
import json
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from uuid import uuid4


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


def test_admin_session_uses_digest_key_minimal_payload_and_fixed_ttl() -> None:
    session_module = load_module("app.infrastructure.admin_session")
    redis = FakeRedisOperations()
    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    store = session_module.AdminSessionStore(redis, clock=lambda: now)
    token = "raw-session-token-that-must-stay-private"
    admin_id = uuid4()

    session = run(
        store.create(
            session_token=token,
            admin_id=admin_id,
            username="admin",
            ttl_seconds=3600,
        )
    )

    assert session.admin_id == admin_id
    assert session.created_at == now
    assert session.expires_at == now + timedelta(seconds=3600)
    assert len(redis.values) == 1
    key = next(iter(redis.values))
    payload = json.loads(redis.values[key])
    assert key.startswith("admin_session:")
    assert token not in key
    assert token not in redis.values[key]
    assert redis.ttls[key] == 3600
    assert set(payload) == {"admin_id", "username", "created_at", "expires_at"}
    assert "password" not in redis.values[key]


def test_admin_session_can_be_read_deleted_and_rejects_expired_payload() -> None:
    session_module = load_module("app.infrastructure.admin_session")
    redis = FakeRedisOperations()
    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    store = session_module.AdminSessionStore(redis, clock=lambda: now)
    token = "opaque-token"
    created = run(
        store.create(
            session_token=token,
            admin_id=uuid4(),
            username="admin",
            ttl_seconds=60,
        )
    )

    assert run(store.read(token)) == created

    store._clock = lambda: now + timedelta(seconds=61)
    assert run(store.read(token)) is None

    run(store.delete(token))
    assert redis.values == {}


def test_admin_session_rejects_timezone_naive_timestamp_as_malformed() -> None:
    session_module = load_module("app.infrastructure.admin_session")
    redis = FakeRedisOperations()
    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    store = session_module.AdminSessionStore(redis, clock=lambda: now)
    token = "opaque-token"
    redis.values[store._key(token)] = json.dumps(
        {
            "admin_id": str(uuid4()),
            "username": "admin",
            "created_at": "2026-07-14T10:00:00",
            "expires_at": "2026-07-14T11:00:00",
        }
    )

    assert run(store.read(token)) is None


def test_login_limiter_hashes_identity_uses_atomic_increment_and_clears_success() -> None:
    limiter_module = load_module("app.infrastructure.admin_login_limiter")
    redis = FakeRedisOperations()
    limiter = limiter_module.AdminLoginRateLimiter(
        redis,
        max_failures=2,
        window_seconds=300,
    )

    assert run(limiter.is_limited(" Admin ", "127.0.0.1")) is False
    assert run(limiter.record_failure(" Admin ", "127.0.0.1")) == 1
    assert run(limiter.record_failure("admin", "127.0.0.1")) == 2
    assert run(limiter.is_limited("admin", "127.0.0.1")) is True

    key, ttl = redis.increment_calls[0]
    assert key.startswith("admin_login_failures:")
    assert "admin" not in key.removeprefix("admin_login_failures:")
    assert "127.0.0.1" not in key
    assert ttl == 300
    assert redis.ttls[key] == 300

    run(limiter.clear("admin", "127.0.0.1"))
    assert run(limiter.is_limited("admin", "127.0.0.1")) is False
