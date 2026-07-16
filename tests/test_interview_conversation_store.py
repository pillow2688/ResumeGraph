import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.infrastructure.interview_conversation import (
    ConversationOwnershipError,
    ConversationRequestStatus,
    ConversationTurn,
    InterviewConversationStore,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None:
        self.values[key] = value
        self.ttls[key] = ttl_seconds

    async def set_if_absent_with_ttl(self, key: str, value: str, ttl_seconds: int) -> bool:
        if key in self.values:
            return False
        self.values[key] = value
        self.ttls[key] = ttl_seconds
        return True

    async def compare_and_delete(self, key: str, expected_value: str) -> bool:
        if self.values.get(key) != expected_value:
            return False
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        return True

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.ttls.pop(key, None)

    async def increment_with_ttl(self, key: str, ttl_seconds: int) -> int:
        del key, ttl_seconds
        return 1


def test_conversation_is_ephemeral_owner_bound_and_contains_no_raw_session() -> None:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    redis = FakeRedis()
    store = InterviewConversationStore(redis, max_turns=8, clock=lambda: now)
    raw_session = "raw-recruiter-session-secret"
    grant_id = uuid4()

    conversation = asyncio.run(
        store.create(
            session_token=raw_session,
            grant_id=grant_id,
            ttl_seconds=3600,
            expires_at_limit=now + timedelta(hours=2),
        )
    )

    key = store.conversation_key(conversation.conversation_id)
    assert key.startswith("interview_conversation:")
    assert redis.ttls[key] == 3600
    assert raw_session not in key
    assert raw_session not in redis.values[key]
    assert conversation.recruiter_session_id != raw_session
    assert conversation.grant_id == grant_id
    assert conversation.recent_turns == []
    assert (
        asyncio.run(
            store.read_owned(
                conversation.conversation_id,
                session_token=raw_session,
                grant_id=grant_id,
            )
        )
        == conversation
    )


def test_conversation_rejects_a_different_recruiter_or_grant() -> None:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    store = InterviewConversationStore(FakeRedis(), max_turns=8, clock=lambda: now)
    conversation = asyncio.run(
        store.create(
            session_token="owner-session",
            grant_id=uuid4(),
            ttl_seconds=3600,
            expires_at_limit=now + timedelta(hours=2),
        )
    )

    with pytest.raises(ConversationOwnershipError):
        asyncio.run(
            store.read_owned(
                conversation.conversation_id,
                session_token="different-session",
                grant_id=conversation.grant_id,
            )
        )
    with pytest.raises(ConversationOwnershipError):
        asyncio.run(
            store.read_owned(
                conversation.conversation_id,
                session_token="owner-session",
                grant_id=uuid4(),
            )
        )


def test_conversation_keeps_only_bounded_summaries_and_expires() -> None:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    redis = FakeRedis()
    store = InterviewConversationStore(redis, max_turns=2, clock=lambda: now)
    conversation = asyncio.run(
        store.create(
            session_token="owner-session",
            grant_id=uuid4(),
            ttl_seconds=60,
            expires_at_limit=now + timedelta(hours=1),
        )
    )
    updated = conversation.model_copy(
        update={
            "recent_turns": [
                ConversationTurn(question_summary=f"q{index}", answer_summary=f"a{index}")
                for index in range(3)
            ],
            "updated_at": now,
        }
    )
    asyncio.run(store.save_owned(updated, session_token="owner-session"))
    reread = asyncio.run(
        store.read_owned(
            conversation.conversation_id,
            session_token="owner-session",
            grant_id=conversation.grant_id,
        )
    )

    assert [turn.question_summary for turn in reread.recent_turns] == ["q1", "q2"]
    store._clock = lambda: now + timedelta(seconds=61)
    assert (
        asyncio.run(
            store.read_owned(
                conversation.conversation_id,
                session_token="owner-session",
                grant_id=conversation.grant_id,
            )
        )
        is None
    )


def test_conversation_lock_and_request_idempotency_are_atomic() -> None:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    store = InterviewConversationStore(FakeRedis(), max_turns=8, clock=lambda: now)
    conversation_id, request_id = uuid4(), uuid4()

    lock_token = asyncio.run(store.acquire_turn_lock(conversation_id, ttl_seconds=30))
    assert lock_token is not None
    assert asyncio.run(store.acquire_turn_lock(conversation_id, ttl_seconds=30)) is None
    assert asyncio.run(store.release_turn_lock(conversation_id, "wrong-token")) is False
    assert asyncio.run(store.release_turn_lock(conversation_id, lock_token)) is True

    created, pending = asyncio.run(
        store.begin_request(
            conversation_id,
            request_id=request_id,
            question_hash="a" * 64,
            ttl_seconds=3600,
        )
    )
    duplicate_created, duplicate = asyncio.run(
        store.begin_request(
            conversation_id,
            request_id=request_id,
            question_hash="a" * 64,
            ttl_seconds=3600,
        )
    )
    assert created is True and duplicate_created is False
    assert pending == duplicate
    assert pending.status is ConversationRequestStatus.PENDING

    completed = asyncio.run(
        store.complete_request(
            conversation_id,
            request_id=request_id,
            question_hash="a" * 64,
            response_payload={"status": "answered", "answer": "safe"},
            ttl_seconds=3600,
        )
    )
    assert completed.status is ConversationRequestStatus.COMPLETED
    assert completed.response_payload == {"status": "answered", "answer": "safe"}
