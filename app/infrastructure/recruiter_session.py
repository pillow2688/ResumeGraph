from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.core.security import digest_secret
from app.infrastructure.redis import RedisOperations


class RecruiterSessionData(BaseModel):
    grant_id: UUID
    created_at: datetime
    expires_at: datetime
    allowed_project_ids_snapshot: list[UUID] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        if self.created_at.utcoffset() is None or self.expires_at.utcoffset() is None:
            raise ValueError("Session timestamps must include a timezone.")
        if self.expires_at <= self.created_at:
            raise ValueError("Session expiry must be after creation.")
        return self


class RecruiterSessionLifetimeError(ValueError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RecruiterSessionStore:
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
        return f"recruiter_session:{digest_secret(session_token)}"

    async def create(
        self,
        *,
        session_token: str,
        grant_id: UUID,
        allowed_project_ids_snapshot: Sequence[UUID],
        ttl_seconds: int,
        expires_at_limit: datetime,
    ) -> RecruiterSessionData:
        created_at = self._clock()
        if expires_at_limit.utcoffset() is None:
            raise RecruiterSessionLifetimeError
        effective_ttl_seconds = min(
            ttl_seconds,
            int((expires_at_limit - created_at).total_seconds()),
        )
        if effective_ttl_seconds <= 0:
            raise RecruiterSessionLifetimeError
        session = RecruiterSessionData(
            grant_id=grant_id,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=effective_ttl_seconds),
            allowed_project_ids_snapshot=list(dict.fromkeys(allowed_project_ids_snapshot)),
        )
        await self._redis.set_with_ttl(
            self._key(session_token),
            session.model_dump_json(),
            effective_ttl_seconds,
        )
        return session

    async def read(self, session_token: str) -> RecruiterSessionData | None:
        payload = await self._redis.get(self._key(session_token))
        if payload is None:
            return None
        try:
            session = RecruiterSessionData.model_validate_json(payload)
        except ValidationError:
            return None
        if session.expires_at <= self._clock():
            return None
        return session

    async def delete(self, session_token: str) -> None:
        await self._redis.delete(self._key(session_token))
