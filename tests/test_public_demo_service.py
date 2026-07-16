import asyncio
import importlib
import importlib.util
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.repositories.access_grant import AccessGrantRecord, ProjectRecord
from app.repositories.public_demo import (
    PublicDemoRecord,
    PublicDemoRepositoryUnavailableError,
)
from app.services.access_grant import (
    AccessControlUnavailableError,
    AccessGrantNotFoundError,
    InvalidAccessGrantError,
)

NOW = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)
UNAVAILABLE_MESSAGE = "AI Interview 尚未开放"


def load_service_module():
    name = "app.services.public_demo"
    assert importlib.util.find_spec(name) is not None, f"{name} must exist"
    return importlib.import_module(name)


def load_schema_module():
    name = "app.schemas.public_demo"
    assert importlib.util.find_spec(name) is not None, f"{name} must exist"
    return importlib.import_module(name)


def make_grant(**overrides: object) -> AccessGrantRecord:
    values: dict[str, object] = {
        "id": uuid4(),
        "name": "Public Demo Grant",
        "token_hash": "digest-only",
        "expires_at": NOW + timedelta(days=7),
        "max_requests": 100,
        "request_count": 10,
        "revoked_at": None,
        "created_at": NOW - timedelta(days=1),
        "projects": (ProjectRecord(id=uuid4(), name="ResumeGraph"),),
    }
    values.update(overrides)
    return AccessGrantRecord(**values)


def make_config(grant_id: UUID, *, enabled: bool = True) -> PublicDemoRecord:
    return PublicDemoRecord(
        id=1,
        candidate_name="马腾飞",
        default_access_grant_id=grant_id,
        enabled=enabled,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeRepository:
    def __init__(self, record: PublicDemoRecord | None) -> None:
        self.record = record
        self.unavailable = False
        self.upsert_kwargs: dict[str, object] | None = None

    async def get(self) -> PublicDemoRecord | None:
        if self.unavailable:
            raise PublicDemoRepositoryUnavailableError
        return self.record

    async def upsert(self, **kwargs: object) -> PublicDemoRecord:
        if self.unavailable:
            raise PublicDemoRepositoryUnavailableError
        self.upsert_kwargs = kwargs
        self.record = make_config(
            kwargs["default_access_grant_id"],
            enabled=bool(kwargs["enabled"]),
        )
        self.record = replace(self.record, candidate_name=str(kwargs["candidate_name"]))
        return self.record


class FakeAccessService:
    def __init__(self, grant: AccessGrantRecord | None) -> None:
        self.grant = grant
        self.unavailable = False
        self.session_result = object()
        self.created_for: UUID | None = None

    def _load(self, grant_id: UUID) -> AccessGrantRecord:
        if self.unavailable:
            raise AccessControlUnavailableError
        if self.grant is None or self.grant.id != grant_id:
            raise AccessGrantNotFoundError
        return self.grant

    def _validate(self, grant_id: UUID) -> AccessGrantRecord:
        grant = self._load(grant_id)
        if (
            grant.revoked_at is not None
            or grant.expires_at <= NOW
            or grant.request_count >= grant.max_requests
            or not grant.projects
        ):
            raise InvalidAccessGrantError
        return grant

    async def get_grant(self, grant_id: UUID):
        schemas = importlib.import_module("app.schemas.access_grant")
        grant = self._load(grant_id)
        return schemas.AccessGrantMetadata(
            id=grant.id,
            name=grant.name,
            expires_at=grant.expires_at,
            max_requests=grant.max_requests,
            request_count=grant.request_count,
            revoked_at=grant.revoked_at,
            created_at=grant.created_at,
            projects=[
                schemas.ProjectSummary(id=project.id, name=project.name)
                for project in grant.projects
            ],
        )

    async def validate_grant_for_session(self, grant_id: UUID):
        self._validate(grant_id)
        return await self.get_grant(grant_id)

    async def create_session_from_grant(self, grant_id: UUID):
        self._validate(grant_id)
        self.created_for = grant_id
        return self.session_result


def make_service(
    config: PublicDemoRecord | None,
    grant: AccessGrantRecord | None,
):
    service_module = load_service_module()
    repository = FakeRepository(config)
    access_service = FakeAccessService(grant)
    return service_module.PublicDemoService(repository, access_service), repository, access_service


def test_update_schema_normalizes_candidate_name_and_rejects_empty_value() -> None:
    schemas = load_schema_module()
    request = schemas.PublicDemoUpdateRequest(
        candidate_name="  马腾飞  ",
        default_access_grant_id=uuid4(),
        enabled=True,
    )

    assert request.candidate_name == "马腾飞"
    with pytest.raises(ValidationError):
        schemas.PublicDemoUpdateRequest(
            candidate_name="   ",
            default_access_grant_id=uuid4(),
            enabled=True,
        )


def test_available_config_returns_candidate_and_creates_session_from_bound_grant() -> None:
    grant = make_grant()
    service, _repository, access = make_service(make_config(grant.id), grant)

    status = asyncio.run(service.get_public_status())
    session = asyncio.run(service.create_public_session())

    assert status.available is True
    assert status.candidate_name == "马腾飞"
    assert status.message is None
    assert session is access.session_result
    assert access.created_for == grant.id


@pytest.mark.parametrize("state", ["missing_config", "disabled"])
def test_missing_or_disabled_config_returns_friendly_unavailable_status(state: str) -> None:
    grant = make_grant()
    config = None if state == "missing_config" else make_config(grant.id, enabled=False)
    service, _repository, _access = make_service(config, grant)

    status = asyncio.run(service.get_public_status())

    assert status.model_dump(exclude_none=True) == {
        "available": False,
        "message": UNAVAILABLE_MESSAGE,
    }


@pytest.mark.parametrize(
    "grant",
    [
        make_grant(revoked_at=NOW),
        make_grant(expires_at=NOW),
        make_grant(request_count=100),
    ],
    ids=["revoked", "expired", "quota_exhausted"],
)
def test_invalid_bound_grant_returns_friendly_unavailable_status(
    grant: AccessGrantRecord,
) -> None:
    service, _repository, _access = make_service(make_config(grant.id), grant)

    status = asyncio.run(service.get_public_status())

    assert status.available is False
    assert status.message == UNAVAILABLE_MESSAGE


def test_admin_update_validates_enabled_grant_and_returns_scope() -> None:
    grant = make_grant()
    service, repository, _access = make_service(None, grant)

    result = asyncio.run(
        service.update_config(
            candidate_name="马腾飞",
            default_access_grant_id=grant.id,
            enabled=True,
        )
    )

    assert repository.upsert_kwargs == {
        "candidate_name": "马腾飞",
        "default_access_grant_id": grant.id,
        "enabled": True,
    }
    assert result.configured is True
    assert result.default_access_grant is not None
    assert result.default_access_grant.projects[0].name == "ResumeGraph"


def test_admin_can_disable_a_revoked_grant_but_cannot_enable_it() -> None:
    grant = make_grant(revoked_at=NOW)
    service_module = load_service_module()
    service, _repository, _access = make_service(make_config(grant.id), grant)

    disabled = asyncio.run(
        service.update_config(
            candidate_name="马腾飞",
            default_access_grant_id=grant.id,
            enabled=False,
        )
    )
    assert disabled.enabled is False

    with pytest.raises(service_module.InvalidPublicDemoConfigError):
        asyncio.run(
            service.update_config(
                candidate_name="马腾飞",
                default_access_grant_id=grant.id,
                enabled=True,
            )
        )


@pytest.mark.parametrize("dependency", ["repository", "access"])
def test_dependency_failures_are_translated_without_details(dependency: str) -> None:
    service_module = load_service_module()
    grant = make_grant()
    service, repository, access = make_service(make_config(grant.id), grant)
    if dependency == "repository":
        repository.unavailable = True
    else:
        access.unavailable = True

    with pytest.raises(service_module.PublicDemoServiceUnavailableError):
        asyncio.run(service.get_public_status())
