from app.core.security import digest_secret
from app.infrastructure.redis import RedisOperations


class FailureRateLimiter:
    """Small Redis-backed fixed-window limiter for failed authentication attempts."""

    def __init__(
        self,
        redis: RedisOperations,
        *,
        key_prefix: str,
        max_failures: int,
        window_seconds: int,
    ) -> None:
        self._redis = redis
        self._key_prefix = key_prefix
        self._max_failures = max_failures
        self._window_seconds = window_seconds

    def _key(self, identifier: str) -> str:
        return f"{self._key_prefix}:{digest_secret(identifier)}"

    async def is_limited(self, identifier: str) -> bool:
        count = await self._redis.get(self._key(identifier))
        if count is None:
            return False
        try:
            return int(count) >= self._max_failures
        except ValueError:
            return True

    async def record_failure(self, identifier: str) -> int:
        return await self._redis.increment_with_ttl(
            self._key(identifier),
            self._window_seconds,
        )

    async def clear(self, identifier: str) -> None:
        await self._redis.delete(self._key(identifier))
