import asyncio
import importlib
import importlib.util
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.core.security import digest_access_token, generate_access_token
from app.infrastructure.health import DependencyUnavailableError
from app.infrastructure.recruiter_session import RecruiterSessionData
from app.repositories.access_grant import (
    AccessGrantProjectNotFoundError,
    AccessGrantRecord,
    AccessGrantRepositoryUnavailableError,
    ProjectRecord,
)

NOW = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
PEPPER = "fictional-access-token-pepper-for-tests"


def load_service_module():
    name = "app.services.access_grant"
    assert importlib.util.find_spec(name) is not None, f"{name} must exist"
    return importlib.import_module(name)


def load_schema_module():
    name = "app.schemas.access_grant"
    assert importlib.util.find_spec(name) is not None, f"{name} must exist"
    return importlib.import_module(name)


def make_record(
    *,
    token_hash: str = "digest-only",
    expires_at: datetime = NOW + timedelta(hours=2),
    revoked_at: datetime | None = None,
    max_requests: int = 100,
    request_count: int = 10,
    projects: tuple[ProjectRecord, ...] | None = None,
) -> AccessGrantRecord:
    return AccessGrantRecord(
        id=uuid4(),
        name="Fictional Company - Interview",
        token_hash=token_hash,
        expires_at=expires_at,
        max_requests=max_requests,
        request_count=request_count,
        revoked_at=revoked_at,
        created_at=NOW - timedelta(days=1),
        projects=projects
        if projects is not None
        else (ProjectRecord(id=uuid4(), name="Fictional ResumeGraph"),),
    )


class FakeRepository:
    def __init__(self, records: list[AccessGrantRecord] | None = None) -> None:
        self.records = {record.id: record for record in records or []}
        self.projects = {
            uuid4(): "Fictional ResumeGraph",
            uuid4(): "Fictional Search Service",
        }
        self.created_kwargs: dict[str, object] | None = None
        self.missing_project = False
        self.unavailable = False

    def _check(self) -> None:
        if self.unavailable:
            raise AccessGrantRepositoryUnavailableError

    async def create(self, **kwargs) -> AccessGrantRecord:
        self._check()
        if self.missing_project:
            raise AccessGrantProjectNotFoundError
        self.created_kwargs = kwargs
        project_ids = kwargs["project_ids"]
        record = AccessGrantRecord(
            id=uuid4(),
            name=kwargs["name"],
            token_hash=kwargs["token_hash"],
            expires_at=kwargs["expires_at"],
            max_requests=kwargs["max_requests"],
            request_count=0,
            revoked_at=None,
            created_at=NOW,
            projects=tuple(
                ProjectRecord(id=project_id, name=self.projects[project_id])
                for project_id in project_ids
            ),
        )
        self.records[record.id] = record
        return record

    async def list(self) -> list[AccessGrantRecord]:
        self._check()
        return list(self.records.values())

    async def get_by_id(self, grant_id: UUID) -> AccessGrantRecord | None:
        self._check()
        return self.records.get(grant_id)

    async def get_by_token_hash(self, token_hash: str) -> AccessGrantRecord | None:
        self._check()
        return next(
            (record for record in self.records.values() if record.token_hash == token_hash),
            None,
        )

    async def revoke(
        self,
        grant_id: UUID,
        *,
        revoked_at: datetime,
    ) -> AccessGrantRecord | None:
        self._check()
        record = self.records.get(grant_id)
        if record is None:
            return None
        if record.revoked_at is None:
            record = replace(record, revoked_at=revoked_at)
            self.records[grant_id] = record
        return record


class FakeSessionStore:
    def __init__(self) -> None:
        self.session: RecruiterSessionData | None = None
        self.created_token: str | None = None
        self.created_ttl: int | None = None
        self.deleted_token: str | None = None
        self.unavailable = False

    def _check(self) -> None:
        if self.unavailable:
            raise DependencyUnavailableError("redis")

    async def create(
        self,
        *,
        session_token: str,
        grant_id: UUID,
        allowed_project_ids_snapshot: list[UUID],
        ttl_seconds: int,
        expires_at_limit: datetime,
    ) -> RecruiterSessionData:
        self._check()
        self.created_token = session_token
        self.created_ttl = min(
            ttl_seconds,
            int((expires_at_limit - NOW).total_seconds()),
        )
        self.session = RecruiterSessionData(
            grant_id=grant_id,
            created_at=NOW,
            expires_at=NOW + timedelta(seconds=self.created_ttl),
            allowed_project_ids_snapshot=allowed_project_ids_snapshot,
        )
        return self.session

    async def read(self, _session_token: str) -> RecruiterSessionData | None:
        self._check()
        return self.session

    async def delete(self, session_token: str) -> None:
        self._check()
        self.deleted_token = session_token
        self.session = None


class FakeLimiter:
    def __init__(self) -> None:
        self.count = 0
        self.cleared = False
        self.unavailable = False

    def _check(self) -> None:
        if self.unavailable:
            raise DependencyUnavailableError("redis")

    async def is_limited(self, _identifier: str) -> bool:
        self._check()
        return self.count >= 10

    async def record_failure(self, _identifier: str) -> int:
        self._check()
        self.count += 1
        return self.count

    async def clear(self, _identifier: str) -> None:
        self._check()
        self.count = 0
        self.cleared = True


def make_service(
    repository: FakeRepository,
    *,
    store: FakeSessionStore | None = None,
    limiter: FakeLimiter | None = None,
):
    service_module = load_service_module()
    return service_module.AccessGrantService(
        repository,
        store or FakeSessionStore(),
        limiter or FakeLimiter(),
        access_token_pepper=PEPPER,
        recruiter_session_ttl_seconds=3600,
        access_exchange_failure_limit=10,
        dependency_timeout_seconds=1,
        clock=lambda: NOW,
    )


def test_create_schema_normalizes_name_deduplicates_projects_and_requires_timezone() -> None:
    schemas = load_schema_module()
    first = uuid4()
    second = uuid4()
    request = schemas.AccessGrantCreateRequest(
        name="  Fictional Company - Interview  ",
        expires_at=NOW + timedelta(days=7),
        max_requests=100,
        project_ids=[first, first, second],
    )

    assert request.name == "Fictional Company - Interview"
    assert request.project_ids == [first, second]

    with pytest.raises(ValidationError):
        schemas.AccessGrantCreateRequest(
            name="Fictional",
            expires_at=datetime(2026, 7, 15, 10, 0),
            max_requests=100,
            project_ids=[first],
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "   "},
        {"max_requests": 0},
        {"max_requests": 1_000_001},
        {"project_ids": []},
    ],
)
def test_create_schema_rejects_invalid_bounds(overrides: dict[str, object]) -> None:
    schemas = load_schema_module()
    values = {
        "name": "Fictional Company",
        "expires_at": NOW + timedelta(days=7),
        "max_requests": 100,
        "project_ids": [uuid4()],
    }
    values.update(overrides)

    with pytest.raises(ValidationError):
        schemas.AccessGrantCreateRequest(**values)


def test_create_grant_generates_one_time_token_and_persists_only_hmac_digest() -> None:
    repository = FakeRepository()
    service = make_service(repository)
    project_ids = list(repository.projects)

    result = asyncio.run(
        service.create_grant(
            name="Fictional Company",
            expires_at=NOW + timedelta(days=7),
            max_requests=100,
            project_ids=[project_ids[0], project_ids[0], project_ids[1]],
        )
    )

    assert result.access_token.startswith("rsg_")
    assert repository.created_kwargs is not None
    assert repository.created_kwargs["project_ids"] == project_ids
    assert repository.created_kwargs["token_hash"] == digest_access_token(
        result.access_token,
        PEPPER,
    )
    assert repository.created_kwargs["token_hash"] != result.access_token
    assert "token_hash" not in result.grant.model_dump()
    assert "access_token" not in result.grant.model_dump()


def test_create_grant_rejects_past_expiry_and_missing_project_without_partial_success() -> None:
    service_module = load_service_module()
    repository = FakeRepository()
    service = make_service(repository)

    with pytest.raises(service_module.InvalidAccessGrantRequestError):
        asyncio.run(
            service.create_grant(
                name="Fictional Company",
                expires_at=NOW,
                max_requests=100,
                project_ids=[next(iter(repository.projects))],
            )
        )

    repository.missing_project = True
    with pytest.raises(service_module.InvalidProjectScopeError):
        asyncio.run(
            service.create_grant(
                name="Fictional Company",
                expires_at=NOW + timedelta(days=1),
                max_requests=100,
                project_ids=[uuid4()],
            )
        )


def test_list_detail_and_idempotent_revoke_return_safe_metadata() -> None:
    service_module = load_service_module()
    record = make_record()
    repository = FakeRepository([record])
    service = make_service(repository)

    listed = asyncio.run(service.list_grants())
    detail = asyncio.run(service.get_grant(record.id))
    first_revoke = asyncio.run(service.revoke_grant(record.id))
    second_revoke = asyncio.run(service.revoke_grant(record.id))

    assert listed[0].id == record.id
    assert detail.id == record.id
    assert "token_hash" not in detail.model_dump()
    assert first_revoke.revoked_at == NOW
    assert second_revoke.revoked_at == NOW

    with pytest.raises(service_module.AccessGrantNotFoundError):
        asyncio.run(service.get_grant(uuid4()))


def test_valid_access_token_creates_bounded_session_without_consuming_quota() -> None:
    raw_token = generate_access_token()
    record = make_record(
        token_hash=digest_access_token(raw_token, PEPPER),
        expires_at=NOW + timedelta(minutes=30),
    )
    repository = FakeRepository([record])
    store = FakeSessionStore()
    limiter = FakeLimiter()
    service = make_service(repository, store=store, limiter=limiter)

    result = asyncio.run(service.exchange_access_token(raw_token, "127.0.0.1"))

    assert result.session_token == store.created_token
    assert result.session_token != raw_token
    assert result.ttl_seconds == 1800
    assert store.created_ttl == 1800
    assert result.principal.allowed_project_ids == [record.projects[0].id]
    assert result.principal.remaining_requests == 90
    assert repository.records[record.id].request_count == 10
    assert limiter.cleared is True


@pytest.mark.parametrize(
    "record_overrides",
    [
        None,
        {"expires_at": NOW},
        {"revoked_at": NOW - timedelta(minutes=1)},
        {"request_count": 100},
        {"projects": ()},
    ],
)
def test_invalid_access_grant_states_share_one_error_and_count_failure(
    record_overrides: dict[str, object] | None,
) -> None:
    service_module = load_service_module()
    raw_token = generate_access_token()
    records: list[AccessGrantRecord] = []
    if record_overrides is not None:
        record = make_record(token_hash=digest_access_token(raw_token, PEPPER))
        record = replace(record, **record_overrides)
        records.append(record)
    limiter = FakeLimiter()
    service = make_service(FakeRepository(records), limiter=limiter)

    with pytest.raises(service_module.InvalidAccessGrantError):
        asyncio.run(service.exchange_access_token(raw_token, "127.0.0.1"))

    assert limiter.count == 1


def test_ten_malformed_tokens_are_counted_and_eleventh_attempt_is_rate_limited() -> None:
    service_module = load_service_module()
    limiter = FakeLimiter()
    limiter.count = 9
    service = make_service(FakeRepository(), limiter=limiter)

    with pytest.raises(service_module.InvalidAccessGrantError):
        asyncio.run(service.exchange_access_token("malformed", "127.0.0.1"))

    assert limiter.count == 10
    with pytest.raises(service_module.AccessExchangeRateLimitedError):
        asyncio.run(service.exchange_access_token("malformed", "127.0.0.1"))
    assert limiter.count == 10


def test_current_recruiter_reloads_database_scope_and_ignores_redis_snapshot() -> None:
    record = make_record()
    repository = FakeRepository([record])
    store = FakeSessionStore()
    store.session = RecruiterSessionData(
        grant_id=record.id,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        allowed_project_ids_snapshot=[uuid4()],
    )
    service = make_service(repository, store=store)

    principal = asyncio.run(service.get_current_recruiter("opaque-session-token"))

    assert principal.allowed_project_ids == [record.projects[0].id]
    assert principal.allowed_projects[0].name == record.projects[0].name


def test_interview_session_revalidation_keeps_an_exhausted_grant_authenticated() -> None:
    record = make_record(request_count=100, max_requests=100)
    repository = FakeRepository([record])
    store = FakeSessionStore()
    store.session = RecruiterSessionData(
        grant_id=record.id,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        allowed_project_ids_snapshot=[record.projects[0].id],
    )
    service = make_service(repository, store=store)

    principal = asyncio.run(service.get_current_recruiter_for_interview("opaque-session-token"))

    assert principal.grant_id == record.id
    assert principal.remaining_requests == 0


@pytest.mark.parametrize("invalid_state", ["missing", "revoked", "expired", "exhausted", "empty"])
def test_current_recruiter_rejects_invalid_current_database_grant(invalid_state: str) -> None:
    service_module = load_service_module()
    record = make_record()
    if invalid_state == "revoked":
        record = replace(record, revoked_at=NOW)
    elif invalid_state == "expired":
        record = replace(record, expires_at=NOW)
    elif invalid_state == "exhausted":
        record = replace(record, request_count=record.max_requests)
    elif invalid_state == "empty":
        record = replace(record, projects=())
    repository = FakeRepository([] if invalid_state == "missing" else [record])
    store = FakeSessionStore()
    store.session = RecruiterSessionData(
        grant_id=record.id,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        allowed_project_ids_snapshot=[uuid4()],
    )
    service = make_service(repository, store=store)

    with pytest.raises(service_module.InvalidRecruiterSessionError):
        asyncio.run(service.get_current_recruiter("opaque-session-token"))


@pytest.mark.parametrize("failure_source", ["repository", "session", "limiter"])
def test_dependency_failures_are_sanitized(failure_source: str) -> None:
    service_module = load_service_module()
    repository = FakeRepository()
    store = FakeSessionStore()
    limiter = FakeLimiter()
    if failure_source == "repository":
        repository.unavailable = True
    elif failure_source == "session":
        store.unavailable = True
        store.session = None
    else:
        limiter.unavailable = True
    service = make_service(repository, store=store, limiter=limiter)

    with pytest.raises(service_module.AccessControlUnavailableError) as raised:
        if failure_source == "session":
            asyncio.run(service.get_current_recruiter("opaque-session-token"))
        else:
            asyncio.run(service.exchange_access_token(generate_access_token(), "127.0.0.1"))

    assert "redis" not in str(raised.value).lower()
    assert "postgresql" not in str(raised.value).lower()


def test_recruiter_logout_deletes_only_presented_session() -> None:
    store = FakeSessionStore()
    service = make_service(FakeRepository(), store=store)

    asyncio.run(service.logout("opaque-recruiter-session"))

    assert store.deleted_token == "opaque-recruiter-session"
