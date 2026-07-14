import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.security import hash_password
from app.infrastructure.admin_login_limiter import AdminLoginRateLimiter
from app.infrastructure.admin_session import AdminSessionStore
from app.infrastructure.failure_limiter import FailureRateLimiter
from app.infrastructure.recruiter_session import RecruiterSessionStore
from app.main import create_app
from app.models import AdminUser
from app.repositories.access_grant import (
    AccessGrantProjectNotFoundError,
    AccessGrantRecord,
)
from app.repositories.access_grant import (
    ProjectRecord as GrantProjectRecord,
)
from app.repositories.project import (
    ProjectDeleteOutcome,
    ProjectRecord,
    ProjectRepositoryUnavailableError,
)
from app.services.access_grant import AccessGrantService
from app.services.admin_auth import AdminAuthService
from app.services.project import ProjectService

NOW = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
ADMIN_PASSWORD = "fictional admin password"
PEPPER = "fictional-project-api-access-token-pepper"


class FakeHealthDependency:
    async def check_health(self) -> None:
        pass

    async def close(self) -> None:
        pass


class InMemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None:
        self.values[key] = value
        self.ttls[key] = ttl_seconds

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.ttls.pop(key, None)

    async def increment_with_ttl(self, key: str, ttl_seconds: int) -> int:
        count = int(self.values.get(key, "0")) + 1
        self.values[key] = str(count)
        self.ttls.setdefault(key, ttl_seconds)
        return count


class InMemoryAdminRepository:
    def __init__(self) -> None:
        self.user = AdminUser(
            id=uuid4(),
            username="admin",
            password_hash=hash_password(ADMIN_PASSWORD),
        )

    async def get_by_username(self, username: str) -> AdminUser | None:
        return self.user if username == self.user.username else None

    async def get_by_id(self, admin_id: UUID) -> AdminUser | None:
        return self.user if admin_id == self.user.id else None


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, ProjectRecord] = {}
        self.grant_links: set[tuple[UUID, UUID]] = set()
        self.document_links: set[tuple[UUID, UUID]] = set()
        self.create_count = 0
        self.unavailable = False
        self.secret = "postgresql://admin:do-not-leak@database/resumegraph"

    def _check(self) -> None:
        if self.unavailable:
            try:
                raise SQLAlchemyError(self.secret)
            except SQLAlchemyError as error:
                raise ProjectRepositoryUnavailableError from error

    async def create(self, *, name: str, description: str) -> ProjectRecord:
        self._check()
        self.create_count += 1
        timestamp = NOW + timedelta(seconds=self.create_count)
        record = ProjectRecord(
            id=uuid4(),
            name=name,
            description=description,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.records[record.id] = record
        return record

    async def list(self) -> list[ProjectRecord]:
        self._check()
        return sorted(
            self.records.values(),
            key=lambda record: (record.created_at, str(record.id)),
            reverse=True,
        )

    async def get_by_id(self, project_id: UUID) -> ProjectRecord | None:
        self._check()
        return self.records.get(project_id)

    async def update(
        self,
        project_id: UUID,
        *,
        name: str | None,
        description: str | None,
    ) -> ProjectRecord | None:
        self._check()
        record = self.records.get(project_id)
        if record is None:
            return None
        next_name = record.name if name is None else name
        next_description = record.description if description is None else description
        if next_name == record.name and next_description == record.description:
            return record
        updated = replace(
            record,
            name=next_name,
            description=next_description,
            updated_at=record.updated_at + timedelta(seconds=1),
        )
        self.records[project_id] = updated
        return updated

    async def delete(self, project_id: UUID) -> ProjectDeleteOutcome:
        self._check()
        if project_id not in self.records:
            return ProjectDeleteOutcome.NOT_FOUND
        if any(linked_project_id == project_id for _, linked_project_id in self.grant_links):
            return ProjectDeleteOutcome.IN_USE
        if any(linked_project_id == project_id for _, linked_project_id in self.document_links):
            return ProjectDeleteOutcome.IN_USE
        self.records.pop(project_id)
        return ProjectDeleteOutcome.DELETED


@dataclass(frozen=True)
class GrantState:
    id: UUID
    name: str
    token_hash: str
    expires_at: datetime
    max_requests: int
    request_count: int
    revoked_at: datetime | None
    created_at: datetime
    project_ids: tuple[UUID, ...]


class InMemoryGrantRepository:
    def __init__(self, projects: InMemoryProjectRepository) -> None:
        self.projects = projects
        self.states: dict[UUID, GrantState] = {}
        self.create_count = 0

    def _record(self, state: GrantState) -> AccessGrantRecord:
        projects = tuple(
            sorted(
                (
                    GrantProjectRecord(
                        id=project_id,
                        name=self.projects.records[project_id].name,
                    )
                    for project_id in state.project_ids
                ),
                key=lambda project: (project.name, str(project.id)),
            )
        )
        return AccessGrantRecord(
            id=state.id,
            name=state.name,
            token_hash=state.token_hash,
            expires_at=state.expires_at,
            max_requests=state.max_requests,
            request_count=state.request_count,
            revoked_at=state.revoked_at,
            created_at=state.created_at,
            projects=projects,
        )

    async def create(self, **kwargs) -> AccessGrantRecord:
        project_ids = tuple(kwargs["project_ids"])
        if any(project_id not in self.projects.records for project_id in project_ids):
            raise AccessGrantProjectNotFoundError
        self.create_count += 1
        state = GrantState(
            id=uuid4(),
            name=kwargs["name"],
            token_hash=kwargs["token_hash"],
            expires_at=kwargs["expires_at"],
            max_requests=kwargs["max_requests"],
            request_count=0,
            revoked_at=None,
            created_at=NOW + timedelta(minutes=self.create_count),
            project_ids=project_ids,
        )
        self.states[state.id] = state
        self.projects.grant_links.update((state.id, project_id) for project_id in project_ids)
        return self._record(state)

    async def list(self) -> list[AccessGrantRecord]:
        states = sorted(
            self.states.values(),
            key=lambda state: (state.created_at, str(state.id)),
            reverse=True,
        )
        return [self._record(state) for state in states]

    async def get_by_id(self, grant_id: UUID) -> AccessGrantRecord | None:
        state = self.states.get(grant_id)
        return self._record(state) if state is not None else None

    async def get_by_token_hash(self, token_hash: str) -> AccessGrantRecord | None:
        state = next(
            (state for state in self.states.values() if state.token_hash == token_hash),
            None,
        )
        return self._record(state) if state is not None else None

    async def revoke(
        self,
        grant_id: UUID,
        *,
        revoked_at: datetime,
    ) -> AccessGrantRecord | None:
        state = self.states.get(grant_id)
        if state is None:
            return None
        if state.revoked_at is None:
            state = replace(state, revoked_at=revoked_at)
            self.states[grant_id] = state
        return self._record(state)


def make_settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+asyncpg://resumegraph:local-only@postgres/resumegraph",
        redis_url="redis://redis:6379/0",
        access_token_pepper=PEPPER,
        admin_session_ttl_seconds=3600,
        recruiter_session_ttl_seconds=3600,
        admin_login_max_failures=5,
        admin_login_window_seconds=300,
        access_exchange_failure_limit=10,
        access_exchange_failure_window_seconds=600,
        dependency_timeout_seconds=1,
        cookie_secure=False,
        _env_file=None,
    )


def make_client():
    settings = make_settings()
    redis = InMemoryRedis()
    admin_repository = InMemoryAdminRepository()
    project_repository = InMemoryProjectRepository()
    grant_repository = InMemoryGrantRepository(project_repository)
    admin_service = AdminAuthService(
        admin_repository,
        AdminSessionStore(redis),
        AdminLoginRateLimiter(
            redis,
            max_failures=settings.admin_login_max_failures,
            window_seconds=settings.admin_login_window_seconds,
        ),
        session_ttl_seconds=settings.admin_session_ttl_seconds,
        login_max_failures=settings.admin_login_max_failures,
        dependency_timeout_seconds=settings.dependency_timeout_seconds,
    )
    grant_service = AccessGrantService(
        grant_repository,
        RecruiterSessionStore(redis, clock=lambda: NOW),
        FailureRateLimiter(
            redis,
            key_prefix="access_exchange_failures",
            max_failures=settings.access_exchange_failure_limit,
            window_seconds=settings.access_exchange_failure_window_seconds,
        ),
        access_token_pepper=PEPPER,
        recruiter_session_ttl_seconds=settings.recruiter_session_ttl_seconds,
        access_exchange_failure_limit=settings.access_exchange_failure_limit,
        dependency_timeout_seconds=settings.dependency_timeout_seconds,
        clock=lambda: NOW,
    )
    project_service = ProjectService(
        project_repository,
        dependency_timeout_seconds=settings.dependency_timeout_seconds,
    )
    client = TestClient(
        create_app(
            settings=settings,
            database=FakeHealthDependency(),
            redis=FakeHealthDependency(),
            admin_auth_service=admin_service,
            access_grant_service=grant_service,
            project_service=project_service,
        )
    )
    return client, project_repository, grant_repository, redis, settings


def login_admin(client: TestClient):
    return client.post(
        "/api/v1/admin/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
    )


def create_project(
    client: TestClient,
    *,
    name: str = "ResumeGraph",
    description: str | None = "Fictional description",
):
    payload = {"name": name}
    if description is not None:
        payload["description"] = description
    return client.post("/api/v1/admin/projects", json=payload)


def create_grant(client: TestClient, project_id: UUID):
    return client.post(
        "/api/v1/admin/access-grants",
        json={
            "name": "Fictional Company - Interview",
            "expires_at": (NOW + timedelta(days=7)).isoformat(),
            "max_requests": 100,
            "project_ids": [str(project_id)],
        },
    )


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("post", "/api/v1/admin/projects", {"name": "ResumeGraph"}),
        ("get", "/api/v1/admin/projects", None),
        ("get", f"/api/v1/admin/projects/{uuid4()}", None),
        ("patch", f"/api/v1/admin/projects/{uuid4()}", {"name": "Renamed"}),
        ("delete", f"/api/v1/admin/projects/{uuid4()}", None),
    ],
)
def test_project_endpoints_require_admin_authentication(
    method: str,
    path: str,
    json_body: dict[str, object] | None,
) -> None:
    client, _projects, _grants, _redis, _settings = make_client()

    with client:
        response = client.request(method, path, json=json_body)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_random_admin_cookie_and_recruiter_cookie_cannot_access_project_admin_api() -> None:
    client, _projects, _grants, _redis, settings = make_client()

    with client:
        client.cookies.set(
            settings.admin_session_cookie_name,
            "random-admin-cookie",
            path="/api/v1/admin",
        )
        random_admin = client.get("/api/v1/admin/projects")
        client.cookies.delete(settings.admin_session_cookie_name, path="/api/v1/admin")
        client.cookies.set(
            settings.recruiter_session_cookie_name,
            "random-recruiter-cookie",
            path="/api/v1",
        )
        recruiter_only = create_project(client)

    assert random_admin.status_code == 401
    assert recruiter_only.status_code == 401


def test_admin_can_list_empty_projects() -> None:
    client, _projects, _grants, _redis, _settings = make_client()

    with client:
        assert login_admin(client).status_code == 200
        response = client.get("/api/v1/admin/projects")

    assert response.status_code == 200
    assert response.json() == []


def test_admin_creates_normalized_safe_project_with_default_description() -> None:
    client, projects, _grants, _redis, _settings = make_client()

    with client:
        assert login_admin(client).status_code == 200
        response = create_project(
            client,
            name="  ResumeGraph  ",
            description=None,
        )

    assert response.status_code == 201
    assert response.json()["name"] == "ResumeGraph"
    assert response.json()["description"] == ""
    assert set(response.json()) == {
        "id",
        "name",
        "description",
        "created_at",
        "updated_at",
    }
    assert len(projects.records) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "   "},
        {"name": "x" * 201},
        {"name": "ResumeGraph", "description": "x" * 5001},
    ],
)
def test_create_rejects_invalid_project_fields(payload: dict[str, object]) -> None:
    client, projects, _grants, _redis, _settings = make_client()

    with client:
        assert login_admin(client).status_code == 200
        response = client.post("/api/v1/admin/projects", json=payload)

    assert response.status_code == 422
    assert projects.records == {}


def test_create_trims_description_and_list_has_stable_order() -> None:
    client, _projects, _grants, _redis, _settings = make_client()

    with client:
        assert login_admin(client).status_code == 200
        first = create_project(client, name="First", description="  First description  ").json()
        second = create_project(client, name="Second").json()
        listed = client.get("/api/v1/admin/projects")

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [second["id"], first["id"]]
    assert first["description"] == "First description"


def test_project_detail_and_missing_or_invalid_uuid_errors() -> None:
    client, _projects, _grants, _redis, _settings = make_client()

    with client:
        assert login_admin(client).status_code == 200
        created = create_project(client).json()
        detail = client.get(f"/api/v1/admin/projects/{created['id']}")
        missing = client.get(f"/api/v1/admin/projects/{uuid4()}")
        invalid = client.get("/api/v1/admin/projects/not-a-uuid")

    assert detail.status_code == 200
    assert detail.json() == created
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "project_not_found"
    assert invalid.status_code == 422


@pytest.mark.parametrize(
    ("payload", "expected_name", "expected_description"),
    [
        ({"name": "  Renamed  "}, "Renamed", "Fictional description"),
        ({"description": "  Updated  "}, "ResumeGraph", "Updated"),
        ({"description": "   "}, "ResumeGraph", ""),
        ({"name": "Renamed", "description": "Updated"}, "Renamed", "Updated"),
    ],
)
def test_patch_supports_normalized_partial_updates(
    payload: dict[str, object],
    expected_name: str,
    expected_description: str,
) -> None:
    client, _projects, _grants, _redis, _settings = make_client()

    with client:
        assert login_admin(client).status_code == 200
        created = create_project(client).json()
        response = client.patch(f"/api/v1/admin/projects/{created['id']}", json=payload)

    assert response.status_code == 200
    assert response.json()["name"] == expected_name
    assert response.json()["description"] == expected_description
    assert set(response.json()) == set(created)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": None},
        {"name": "   "},
        {"name": "x" * 201},
        {"description": None},
        {"description": "x" * 5001},
    ],
)
def test_patch_rejects_invalid_payload(payload: dict[str, object]) -> None:
    client, projects, _grants, _redis, _settings = make_client()

    with client:
        assert login_admin(client).status_code == 200
        created = create_project(client).json()
        response = client.patch(f"/api/v1/admin/projects/{created['id']}", json=payload)

    assert response.status_code == 422
    assert projects.records[UUID(created["id"])].name == "ResumeGraph"


def test_patch_missing_project_returns_project_not_found() -> None:
    client, _projects, _grants, _redis, _settings = make_client()

    with client:
        assert login_admin(client).status_code == 200
        response = client.patch(
            f"/api/v1/admin/projects/{uuid4()}",
            json={"name": "Renamed"},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


def test_noop_patch_preserves_updated_at() -> None:
    client, _projects, _grants, _redis, _settings = make_client()

    with client:
        assert login_admin(client).status_code == 200
        created = create_project(client).json()
        response = client.patch(
            f"/api/v1/admin/projects/{created['id']}",
            json={"name": created["name"], "description": created["description"]},
        )

    assert response.status_code == 200
    assert response.json()["updated_at"] == created["updated_at"]


def test_delete_unreferenced_project_returns_empty_204_then_404() -> None:
    client, projects, _grants, _redis, _settings = make_client()

    with client:
        assert login_admin(client).status_code == 200
        created = create_project(client).json()
        deleted = client.delete(f"/api/v1/admin/projects/{created['id']}")
        detail = client.get(f"/api/v1/admin/projects/{created['id']}")

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert UUID(created["id"]) not in projects.records
    assert detail.status_code == 404


def test_delete_missing_project_returns_project_not_found() -> None:
    client, _projects, _grants, _redis, _settings = make_client()

    with client:
        assert login_admin(client).status_code == 200
        response = client.delete(f"/api/v1/admin/projects/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


def test_grant_reference_blocks_delete_without_changing_project_or_grant() -> None:
    client, projects, grants, _redis, _settings = make_client()

    with client:
        assert login_admin(client).status_code == 200
        project = create_project(client).json()
        grant = create_grant(client, UUID(project["id"])).json()["grant"]
        state_before = grants.states[UUID(grant["id"])]
        response = client.delete(f"/api/v1/admin/projects/{project['id']}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "project_in_use"
    assert UUID(project["id"]) in projects.records
    assert grants.states[UUID(grant["id"])] == state_before
    assert (UUID(grant["id"]), UUID(project["id"])) in projects.grant_links


def test_document_reference_blocks_delete_without_changing_project_or_document() -> None:
    client, projects, _grants, _redis, _settings = make_client()

    with client:
        assert login_admin(client).status_code == 200
        project = create_project(client).json()
        document_id = uuid4()
        project_id = UUID(project["id"])
        projects.document_links.add((document_id, project_id))
        response = client.delete(f"/api/v1/admin/projects/{project['id']}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "project_in_use"
    assert project_id in projects.records
    assert (document_id, project_id) in projects.document_links


def test_project_crud_is_compatible_with_grant_detail_and_recruiter_me() -> None:
    client, projects, grants, redis, settings = make_client()

    with client:
        assert login_admin(client).status_code == 200
        project = create_project(client, name="Original name").json()
        created_grant = create_grant(client, UUID(project["id"])).json()
        grant_id = UUID(created_grant["grant"]["id"])
        grant_before = grants.states[grant_id]
        exchange = client.post(
            "/api/v1/access/exchange",
            json={"access_token": created_grant["access_token"]},
        )
        assert exchange.status_code == 200
        recruiter_key = next(key for key in redis.values if key.startswith("recruiter_session:"))
        recruiter_session_before = redis.values[recruiter_key]

        renamed = client.patch(
            f"/api/v1/admin/projects/{project['id']}",
            json={"name": "Renamed project"},
        )
        grant_detail = client.get(f"/api/v1/admin/access-grants/{grant_id}")
        recruiter_me = client.get("/api/v1/access/me")

    assert renamed.status_code == 200
    assert grant_detail.json()["projects"][0]["name"] == "Renamed project"
    assert recruiter_me.json()["allowed_projects"][0]["name"] == "Renamed project"
    assert grants.states[grant_id] == grant_before
    assert redis.values[recruiter_key] == recruiter_session_before
    assert json.loads(recruiter_session_before)["grant_id"] == str(grant_id)
    assert settings.admin_session_cookie_name != settings.recruiter_session_cookie_name
    assert projects.records[UUID(project["id"])].name == "Renamed project"


def test_real_recruiter_session_cannot_modify_project_authorization_scope() -> None:
    client, _projects, _grants, _redis, settings = make_client()

    with client:
        assert login_admin(client).status_code == 200
        allowed = create_project(client, name="Allowed").json()
        unauthorized = create_project(client, name="Unauthorized").json()
        created_grant = create_grant(client, UUID(allowed["id"])).json()
        assert (
            client.post(
                "/api/v1/access/exchange",
                json={"access_token": created_grant["access_token"]},
            ).status_code
            == 200
        )
        client.cookies.delete(settings.admin_session_cookie_name, path="/api/v1/admin")
        patch = client.patch(
            f"/api/v1/admin/projects/{unauthorized['id']}",
            json={"name": "Scope widened"},
        )
        delete = client.delete(f"/api/v1/admin/projects/{unauthorized['id']}")
        me = client.get("/api/v1/access/me")

    assert patch.status_code == 401
    assert delete.status_code == 401
    assert [item["id"] for item in me.json()["allowed_projects"]] == [allowed["id"]]


def test_project_database_failure_returns_sanitized_503() -> None:
    client, projects, _grants, _redis, _settings = make_client()
    projects.unavailable = True

    with client:
        assert login_admin(client).status_code == 200
        response = client.get("/api/v1/admin/projects")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "service_unavailable",
            "message": "Project management is temporarily unavailable.",
        }
    }
    assert projects.secret not in response.text
    assert "SQLAlchemyError" not in response.text


def test_project_errors_never_echo_secrets_or_authentication_material() -> None:
    client, _projects, _grants, _redis, settings = make_client()
    secrets = [
        ADMIN_PASSWORD,
        PEPPER,
        settings.database_url.get_secret_value(),
        "raw-token-hash-cookie-secret",
    ]

    with client:
        assert login_admin(client).status_code == 200
        response = client.post(
            "/api/v1/admin/projects",
            json={"name": secrets[-1], "description": [secrets[0]]},
        )

    assert response.status_code == 422
    for secret in secrets:
        assert secret not in response.text
