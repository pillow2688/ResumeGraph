import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.security import digest_secret
from app.infrastructure.redis import RedisOperations


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    question_summary: str = Field(min_length=1, max_length=1_000)
    answer_summary: str = Field(min_length=1, max_length=2_000)


class InterviewConversationData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: UUID
    recruiter_session_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    grant_id: UUID
    recent_turns: list[ConversationTurn] = Field(default_factory=list, max_length=8)
    conversation_summary: str = Field(default="", max_length=10_000)
    active_project_ids: list[UUID] = Field(default_factory=list, max_length=50)
    active_technical_topics: list[str] = Field(default_factory=list, max_length=20)
    turn_count: int = Field(default=0, ge=0, le=10_000)
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        if any(
            value.utcoffset() is None
            for value in (self.created_at, self.updated_at, self.expires_at)
        ):
            raise ValueError("Conversation timestamps must include a timezone.")
        if self.updated_at < self.created_at or self.expires_at <= self.created_at:
            raise ValueError("Conversation timestamps are inconsistent.")
        return self


class ConversationRequestStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ConversationRequestData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    question_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ConversationRequestStatus
    response_payload: dict[str, object] | None = None
    error_code: str | None = Field(default=None, max_length=100)
    updated_at: datetime


class ConversationOwnershipError(Exception):
    pass


class ConversationRequestConflictError(Exception):
    pass


class ConversationExpiredError(Exception):
    pass


class InterviewConversationStore:
    def __init__(
        self,
        redis: RedisOperations,
        *,
        max_turns: int,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not 1 <= max_turns <= 8:
            raise ValueError("Conversation turn limit must be between one and eight.")
        self._redis = redis
        self._max_turns = max_turns
        self._clock = clock

    @staticmethod
    def conversation_key(conversation_id: UUID) -> str:
        return f"interview_conversation:{conversation_id}"

    @staticmethod
    def _lock_key(conversation_id: UUID) -> str:
        return f"interview_conversation_lock:{conversation_id}"

    @staticmethod
    def _request_key(conversation_id: UUID, request_id: UUID) -> str:
        return f"interview_request:{conversation_id}:{request_id}"

    @staticmethod
    def session_fingerprint(session_token: str) -> str:
        return digest_secret(session_token)

    async def create(
        self,
        *,
        session_token: str,
        grant_id: UUID,
        ttl_seconds: int,
        expires_at_limit: datetime,
    ) -> InterviewConversationData:
        now = self._clock()
        if expires_at_limit.utcoffset() is None:
            raise ConversationExpiredError
        effective_ttl = min(ttl_seconds, int((expires_at_limit - now).total_seconds()))
        if effective_ttl <= 0:
            raise ConversationExpiredError
        conversation = InterviewConversationData(
            conversation_id=uuid4(),
            recruiter_session_id=self.session_fingerprint(session_token),
            grant_id=grant_id,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(seconds=effective_ttl),
        )
        await self._redis.set_with_ttl(
            self.conversation_key(conversation.conversation_id),
            conversation.model_dump_json(),
            effective_ttl,
        )
        return conversation

    async def read_owned(
        self,
        conversation_id: UUID,
        *,
        session_token: str,
        grant_id: UUID,
    ) -> InterviewConversationData | None:
        payload = await self._redis.get(self.conversation_key(conversation_id))
        if payload is None:
            return None
        try:
            conversation = InterviewConversationData.model_validate_json(payload)
        except ValidationError:
            return None
        if conversation.expires_at <= self._clock():
            await self._redis.delete(self.conversation_key(conversation_id))
            return None
        owner = self.session_fingerprint(session_token)
        if not hmac.compare_digest(conversation.recruiter_session_id, owner):
            raise ConversationOwnershipError
        if conversation.grant_id != grant_id:
            raise ConversationOwnershipError
        return conversation

    async def save_owned(
        self,
        conversation: InterviewConversationData,
        *,
        session_token: str,
    ) -> InterviewConversationData:
        owner = self.session_fingerprint(session_token)
        if not hmac.compare_digest(conversation.recruiter_session_id, owner):
            raise ConversationOwnershipError
        now = self._clock()
        remaining_ttl = int((conversation.expires_at - now).total_seconds())
        if remaining_ttl <= 0:
            raise ConversationExpiredError
        normalized = conversation.model_copy(
            update={
                "recent_turns": conversation.recent_turns[-self._max_turns :],
                "active_project_ids": list(dict.fromkeys(conversation.active_project_ids)),
                "active_technical_topics": list(
                    dict.fromkeys(conversation.active_technical_topics)
                ),
                "updated_at": now,
            }
        )
        await self._redis.set_with_ttl(
            self.conversation_key(conversation.conversation_id),
            normalized.model_dump_json(),
            remaining_ttl,
        )
        return normalized

    async def delete_owned(
        self,
        conversation_id: UUID,
        *,
        session_token: str,
        grant_id: UUID,
    ) -> bool:
        conversation = await self.read_owned(
            conversation_id,
            session_token=session_token,
            grant_id=grant_id,
        )
        if conversation is None:
            return False
        await self._redis.delete(self.conversation_key(conversation_id))
        return True

    async def acquire_turn_lock(
        self,
        conversation_id: UUID,
        *,
        ttl_seconds: int,
    ) -> str | None:
        token = secrets.token_urlsafe(32)
        acquired = await self._redis.set_if_absent_with_ttl(
            self._lock_key(conversation_id),
            token,
            ttl_seconds,
        )
        return token if acquired else None

    async def release_turn_lock(self, conversation_id: UUID, lock_token: str) -> bool:
        return await self._redis.compare_and_delete(
            self._lock_key(conversation_id),
            lock_token,
        )

    async def begin_request(
        self,
        conversation_id: UUID,
        *,
        request_id: UUID,
        question_hash: str,
        ttl_seconds: int,
    ) -> tuple[bool, ConversationRequestData]:
        request = ConversationRequestData(
            request_id=request_id,
            question_hash=question_hash,
            status=ConversationRequestStatus.PENDING,
            updated_at=self._clock(),
        )
        key = self._request_key(conversation_id, request_id)
        created = await self._redis.set_if_absent_with_ttl(
            key,
            request.model_dump_json(),
            ttl_seconds,
        )
        if created:
            return True, request
        existing = await self.read_request(conversation_id, request_id)
        if existing is None or existing.question_hash != question_hash:
            raise ConversationRequestConflictError
        return False, existing

    async def read_request(
        self,
        conversation_id: UUID,
        request_id: UUID,
    ) -> ConversationRequestData | None:
        payload = await self._redis.get(self._request_key(conversation_id, request_id))
        if payload is None:
            return None
        try:
            return ConversationRequestData.model_validate_json(payload)
        except ValidationError:
            return None

    async def delete_request(self, conversation_id: UUID, request_id: UUID) -> None:
        await self._redis.delete(self._request_key(conversation_id, request_id))

    async def complete_request(
        self,
        conversation_id: UUID,
        *,
        request_id: UUID,
        question_hash: str,
        response_payload: dict[str, object],
        ttl_seconds: int,
    ) -> ConversationRequestData:
        request = ConversationRequestData(
            request_id=request_id,
            question_hash=question_hash,
            status=ConversationRequestStatus.COMPLETED,
            response_payload=response_payload,
            updated_at=self._clock(),
        )
        await self._redis.set_with_ttl(
            self._request_key(conversation_id, request_id),
            request.model_dump_json(),
            ttl_seconds,
        )
        return request

    async def fail_request(
        self,
        conversation_id: UUID,
        *,
        request_id: UUID,
        question_hash: str,
        error_code: str,
        ttl_seconds: int,
    ) -> ConversationRequestData:
        request = ConversationRequestData(
            request_id=request_id,
            question_hash=question_hash,
            status=ConversationRequestStatus.FAILED,
            error_code=error_code,
            updated_at=self._clock(),
        )
        await self._redis.set_with_ttl(
            self._request_key(conversation_id, request_id),
            request.model_dump_json(),
            ttl_seconds,
        )
        return request
