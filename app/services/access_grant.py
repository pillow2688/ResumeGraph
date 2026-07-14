import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.core.security import (
    digest_access_token,
    generate_access_token,
    generate_session_token,
    is_access_token_format_valid,
)
from app.infrastructure.health import DependencyUnavailableError
from app.infrastructure.recruiter_session import (
    RecruiterSessionData,
    RecruiterSessionLifetimeError,
)
from app.repositories.access_grant import (
    AccessGrantProjectNotFoundError,
    AccessGrantRecord,
    AccessGrantRepositoryUnavailableError,
)
from app.schemas.access_grant import AccessGrantMetadata, ProjectSummary, RecruiterPrincipal


class AccessGrantRepositoryBackend(Protocol):
    async def create(
        self,
        *,
        name: str,
        token_hash: str,
        expires_at: datetime,
        max_requests: int,
        project_ids: list[UUID],
    ) -> AccessGrantRecord: ...

    async def list(self) -> list[AccessGrantRecord]: ...

    async def get_by_id(self, grant_id: UUID) -> AccessGrantRecord | None: ...

    async def get_by_token_hash(self, token_hash: str) -> AccessGrantRecord | None: ...

    async def revoke(
        self,
        grant_id: UUID,
        *,
        revoked_at: datetime,
    ) -> AccessGrantRecord | None: ...


class RecruiterSessionBackend(Protocol):
    async def create(
        self,
        *,
        session_token: str,
        grant_id: UUID,
        allowed_project_ids_snapshot: Sequence[UUID],
        ttl_seconds: int,
        expires_at_limit: datetime,
    ) -> RecruiterSessionData: ...

    async def read(self, session_token: str) -> RecruiterSessionData | None: ...

    async def delete(self, session_token: str) -> None: ...


class ExchangeFailureLimiter(Protocol):
    async def is_limited(self, identifier: str) -> bool: ...

    async def record_failure(self, identifier: str) -> int: ...

    async def clear(self, identifier: str) -> None: ...


class InvalidAccessGrantRequestError(Exception):
    pass


class InvalidProjectScopeError(Exception):
    pass


class AccessGrantNotFoundError(Exception):
    pass


class InvalidAccessGrantError(Exception):
    pass


class AccessExchangeRateLimitedError(Exception):
    pass


class InvalidRecruiterSessionError(Exception):
    pass


class AccessControlUnavailableError(Exception):
    def __init__(self) -> None:
        super().__init__("Recruiter access control is temporarily unavailable.")


async def _await_dependency[T](awaitable: Awaitable[T], timeout_seconds: float) -> T:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as error:
        raise AccessControlUnavailableError from error


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_metadata(record: AccessGrantRecord) -> AccessGrantMetadata:
    return AccessGrantMetadata(
        id=record.id,
        name=record.name,
        expires_at=record.expires_at,
        max_requests=record.max_requests,
        request_count=record.request_count,
        revoked_at=record.revoked_at,
        created_at=record.created_at,
        projects=[ProjectSummary(id=project.id, name=project.name) for project in record.projects],
    )


def _is_currently_valid(record: AccessGrantRecord | None, now: datetime) -> bool:
    return bool(
        record is not None
        and record.revoked_at is None
        and record.expires_at > now
        and record.request_count < record.max_requests
        and record.projects
    )


def _to_principal(record: AccessGrantRecord) -> RecruiterPrincipal:
    projects = [ProjectSummary(id=project.id, name=project.name) for project in record.projects]
    return RecruiterPrincipal(
        grant_id=record.id,
        grant_name=record.name,
        allowed_project_ids=[project.id for project in projects],
        grant_expires_at=record.expires_at,
        remaining_requests=record.max_requests - record.request_count,
        allowed_projects=projects,
    )


@dataclass(frozen=True)
class AccessGrantCreationResult:
    grant: AccessGrantMetadata
    access_token: str


@dataclass(frozen=True)
class RecruiterExchangeResult:
    principal: RecruiterPrincipal
    session_token: str
    ttl_seconds: int
    expires_at: datetime


class AccessGrantService:
    def __init__(
        self,
        repository: AccessGrantRepositoryBackend,
        session_store: RecruiterSessionBackend,
        exchange_limiter: ExchangeFailureLimiter,
        *,
        access_token_pepper: str,
        recruiter_session_ttl_seconds: int,
        access_exchange_failure_limit: int,
        dependency_timeout_seconds: float,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._session_store = session_store
        self._exchange_limiter = exchange_limiter
        self._access_token_pepper = access_token_pepper
        self._recruiter_session_ttl_seconds = recruiter_session_ttl_seconds
        self._access_exchange_failure_limit = access_exchange_failure_limit
        self._dependency_timeout_seconds = dependency_timeout_seconds
        self._clock = clock

    async def create_grant(
        self,
        *,
        name: str,
        expires_at: datetime,
        max_requests: int,
        project_ids: list[UUID],
    ) -> AccessGrantCreationResult:
        normalized_name = name.strip()
        unique_project_ids = list(dict.fromkeys(project_ids))
        if (
            not normalized_name
            or len(normalized_name) > 200
            or expires_at.utcoffset() is None
            or expires_at <= self._clock()
            or not 0 < max_requests <= 1_000_000
            or not unique_project_ids
            or len(unique_project_ids) > 100
        ):
            raise InvalidAccessGrantRequestError

        access_token = generate_access_token()
        token_hash = digest_access_token(access_token, self._access_token_pepper)
        try:
            record = await _await_dependency(
                self._repository.create(
                    name=normalized_name,
                    token_hash=token_hash,
                    expires_at=expires_at,
                    max_requests=max_requests,
                    project_ids=unique_project_ids,
                ),
                self._dependency_timeout_seconds,
            )
        except AccessGrantProjectNotFoundError as error:
            raise InvalidProjectScopeError from error
        except AccessGrantRepositoryUnavailableError as error:
            raise AccessControlUnavailableError from error
        return AccessGrantCreationResult(grant=_to_metadata(record), access_token=access_token)

    async def list_grants(self) -> list[AccessGrantMetadata]:
        try:
            records = await _await_dependency(
                self._repository.list(),
                self._dependency_timeout_seconds,
            )
        except AccessGrantRepositoryUnavailableError as error:
            raise AccessControlUnavailableError from error
        return [_to_metadata(record) for record in records]

    async def get_grant(self, grant_id: UUID) -> AccessGrantMetadata:
        record = await self._load_grant(grant_id)
        if record is None:
            raise AccessGrantNotFoundError
        return _to_metadata(record)

    async def revoke_grant(self, grant_id: UUID) -> AccessGrantMetadata:
        try:
            record = await _await_dependency(
                self._repository.revoke(grant_id, revoked_at=self._clock()),
                self._dependency_timeout_seconds,
            )
        except AccessGrantRepositoryUnavailableError as error:
            raise AccessControlUnavailableError from error
        if record is None:
            raise AccessGrantNotFoundError
        return _to_metadata(record)

    async def exchange_access_token(
        self,
        raw_token: str,
        client_host: str,
    ) -> RecruiterExchangeResult:
        try:
            if await _await_dependency(
                self._exchange_limiter.is_limited(client_host),
                self._dependency_timeout_seconds,
            ):
                raise AccessExchangeRateLimitedError
        except DependencyUnavailableError as error:
            raise AccessControlUnavailableError from error

        record = None
        if is_access_token_format_valid(raw_token):
            token_hash = digest_access_token(raw_token, self._access_token_pepper)
            try:
                record = await _await_dependency(
                    self._repository.get_by_token_hash(token_hash),
                    self._dependency_timeout_seconds,
                )
            except AccessGrantRepositoryUnavailableError as error:
                raise AccessControlUnavailableError from error

        now = self._clock()
        if not _is_currently_valid(record, now):
            await self._reject_exchange(client_host)
        assert record is not None

        session_token = generate_session_token()
        principal = _to_principal(record)
        try:
            session = await _await_dependency(
                self._session_store.create(
                    session_token=session_token,
                    grant_id=record.id,
                    allowed_project_ids_snapshot=principal.allowed_project_ids,
                    ttl_seconds=self._recruiter_session_ttl_seconds,
                    expires_at_limit=record.expires_at,
                ),
                self._dependency_timeout_seconds,
            )
        except DependencyUnavailableError as error:
            raise AccessControlUnavailableError from error
        except RecruiterSessionLifetimeError:
            await self._reject_exchange(client_host)

        try:
            await _await_dependency(
                self._exchange_limiter.clear(client_host),
                self._dependency_timeout_seconds,
            )
        except DependencyUnavailableError as error:
            raise AccessControlUnavailableError from error

        ttl_seconds = int((session.expires_at - session.created_at).total_seconds())
        return RecruiterExchangeResult(
            principal=principal,
            session_token=session_token,
            ttl_seconds=ttl_seconds,
            expires_at=session.expires_at,
        )

    async def get_current_recruiter(self, session_token: str) -> RecruiterPrincipal:
        try:
            session = await _await_dependency(
                self._session_store.read(session_token),
                self._dependency_timeout_seconds,
            )
        except DependencyUnavailableError as error:
            raise AccessControlUnavailableError from error
        if session is None:
            raise InvalidRecruiterSessionError

        record = await self._load_grant(session.grant_id)
        if not _is_currently_valid(record, self._clock()):
            raise InvalidRecruiterSessionError
        assert record is not None
        return _to_principal(record)

    async def logout(self, session_token: str) -> None:
        try:
            await _await_dependency(
                self._session_store.delete(session_token),
                self._dependency_timeout_seconds,
            )
        except DependencyUnavailableError as error:
            raise AccessControlUnavailableError from error

    async def _load_grant(self, grant_id: UUID) -> AccessGrantRecord | None:
        try:
            return await _await_dependency(
                self._repository.get_by_id(grant_id),
                self._dependency_timeout_seconds,
            )
        except AccessGrantRepositoryUnavailableError as error:
            raise AccessControlUnavailableError from error

    async def _reject_exchange(self, client_host: str) -> None:
        try:
            failure_count = await _await_dependency(
                self._exchange_limiter.record_failure(client_host),
                self._dependency_timeout_seconds,
            )
        except DependencyUnavailableError as error:
            raise AccessControlUnavailableError from error
        if failure_count > self._access_exchange_failure_limit:
            raise AccessExchangeRateLimitedError
        raise InvalidAccessGrantError
