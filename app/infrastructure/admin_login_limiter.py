from app.core.security import normalize_admin_username
from app.infrastructure.failure_limiter import FailureRateLimiter
from app.infrastructure.redis import RedisOperations


class AdminLoginRateLimiter:
    def __init__(
        self,
        redis: RedisOperations,
        *,
        max_failures: int,
        window_seconds: int,
    ) -> None:
        self._limiter = FailureRateLimiter(
            redis,
            key_prefix="admin_login_failures",
            max_failures=max_failures,
            window_seconds=window_seconds,
        )

    @staticmethod
    def _identifier(username: str, client_host: str) -> str:
        normalized_username = normalize_admin_username(username)
        return f"{normalized_username}\0{client_host}"

    async def is_limited(self, username: str, client_host: str) -> bool:
        return await self._limiter.is_limited(self._identifier(username, client_host))

    async def record_failure(self, username: str, client_host: str) -> int:
        return await self._limiter.record_failure(
            self._identifier(username, client_host),
        )

    async def clear(self, username: str, client_host: str) -> None:
        await self._limiter.clear(self._identifier(username, client_host))
