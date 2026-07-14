from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ValidationError, model_validator

from app.core.security import digest_secret
from app.infrastructure.redis import RedisOperations


class AdminSessionData(BaseModel):
    admin_id: UUID
    username: str
    created_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        if self.created_at.utcoffset() is None or self.expires_at.utcoffset() is None:
            raise ValueError("Session timestamps must include a timezone.")
        if self.expires_at <= self.created_at:
            raise ValueError("Session expiry must be after creation.")
        return self


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AdminSessionStore:
    def __init__(
        self,
        redis: RedisOperations,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._redis = redis
        self._clock = clock

    @staticmethod
    def _key(session_token: str) -> str:
        return f"admin_session:{digest_secret(session_token)}"

    async def create(
        self,
        *,
        session_token: str,
        admin_id: UUID,
        username: str,
        ttl_seconds: int,
    ) -> AdminSessionData:
        created_at = self._clock()
        session = AdminSessionData(
            admin_id=admin_id,
            username=username,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=ttl_seconds),
        )
        await self._redis.set_with_ttl(
            self._key(session_token),
            session.model_dump_json(),
            ttl_seconds,
        )
        return session

    async def read(self, session_token: str) -> AdminSessionData | None:
        payload = await self._redis.get(self._key(session_token))
        if payload is None:
            return None
        try:
            session = AdminSessionData.model_validate_json(payload)
        except ValidationError:
            return None
        if session.expires_at <= self._clock():
            return None
        return session

    async def delete(self, session_token: str) -> None:
        await self._redis.delete(self._key(session_token))
