from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.infrastructure.health import DependencyUnavailableError

_INCREMENT_WITH_TTL_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


class RedisOperations(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def increment_with_ttl(self, key: str, ttl_seconds: int) -> int: ...


class RedisConnection:
    """Own the reusable async Redis client and its connection pool."""

    def __init__(self, url: str, *, timeout_seconds: float = 3.0) -> None:
        self._client: Redis = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
        )

    async def check_health(self) -> None:
        try:
            is_available = await self._client.ping()
        except (RedisError, OSError) as error:
            raise DependencyUnavailableError("redis") from error
        if not is_available:
            raise DependencyUnavailableError("redis")

    async def get(self, key: str) -> str | None:
        try:
            return await self._client.get(key)
        except (RedisError, OSError) as error:
            raise DependencyUnavailableError("redis") from error

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None:
        try:
            await self._client.set(key, value, ex=ttl_seconds)
        except (RedisError, OSError) as error:
            raise DependencyUnavailableError("redis") from error

    async def delete(self, key: str) -> None:
        try:
            await self._client.delete(key)
        except (RedisError, OSError) as error:
            raise DependencyUnavailableError("redis") from error

    async def increment_with_ttl(self, key: str, ttl_seconds: int) -> int:
        try:
            result = await self._client.eval(
                _INCREMENT_WITH_TTL_SCRIPT,
                1,
                key,
                ttl_seconds,
            )
        except (RedisError, OSError) as error:
            raise DependencyUnavailableError("redis") from error
        return int(result)

    async def close(self) -> None:
        await self._client.aclose()
