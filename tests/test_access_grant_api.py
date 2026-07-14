import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import digest_access_token, hash_password
from app.infrastructure.admin_login_limiter import AdminLoginRateLimiter
from app.infrastructure.admin_session import AdminSessionStore
from app.infrastructure.failure_limiter import FailureRateLimiter
from app.infrastructure.health import DependencyUnavailableError
from app.infrastructure.recruiter_session import RecruiterSessionStore
from app.main import create_app
from app.models import AdminUser
from app.repositories.access_grant import (
    AccessGrantProjectNotFoundError,
    AccessGrantRecord,
    AccessGrantRepositoryUnavailableError,
    ProjectRecord,
)
from app.services.access_grant import AccessGrantService
from app.services.admin_auth import AdminAuthService

NOW = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
ADMIN_PASSWORD = "fictional admin password"
PEPPER = "fictional-access-token-pepper-for-api-tests"


class FakeHealthDependency:
    async def check_health(self) -> None:
        pass

    async def close(self) -> None:
        pass


class InMemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.unavailable = False

    def _check(self) -> None:
        if self.unavailable:
            raise DependencyUnavailableError("redis")

    async def get(self, key: str) -> str | None:
        self._check()
        return self.values.get(key)

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None:
        self._check()
        self.values[key] = value
        self.ttls[key] = ttl_seconds

    async def delete(self, key: str) -> None:
        self._check()
        self.values.pop(key, None)
        self.ttls.pop(key, None)

    async def increment_with_ttl(self, key: str, ttl_seconds: int) -> int:
        self._check()
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


class InMemoryGrantRepository:
    def __init__(self) -> None:
        self.projects = {
            uuid4(): "Fictional ResumeGraph",
            uuid4(): "Fictional Search Service",
            uuid4(): "Fictional Unrelated Project",
        }
        self.records: dict[UUID, AccessGrantRecord] = {}
        self.unavailable = False
        self.create_count = 0

    def _check(self) -> None:
        if self.unavailable:
            raise AccessGrantRepositoryUnavailableError

    async def create(self, **kwargs) -> AccessGrantRecord:
        self._check()
        project_ids = kwargs["project_ids"]
        if any(project_id not in self.projects for project_id in project_ids):
            raise AccessGrantProjectNotFoundError
        self.create_count += 1
        record = AccessGrantRecord(
            id=uuid4(),
            name=kwargs["name"],
            token_hash=kwargs["token_hash"],
            expires_at=kwargs["expires_at"],
            max_requests=kwargs["max_requests"],
            request_count=0,
            revoked_at=None,
            created_at=NOW + timedelta(seconds=self.create_count),
            projects=tuple(
                ProjectRecord(id=project_id, name=self.projects[project_id])
                for project_id in project_ids
            ),
        )
        self.records[record.id] = record
        return record

    async def list(self) -> list[AccessGrantRecord]:
        self._check()
        return sorted(
            self.records.values(),
            key=lambda record: (record.created_at, str(record.id)),
            reverse=True,
        )

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
    grant_repository = InMemoryGrantRepository()
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
    access_service = AccessGrantService(
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
    client = TestClient(
        create_app(
            settings=settings,
            database=FakeHealthDependency(),
            redis=FakeHealthDependency(),
            admin_auth_service=admin_service,
            access_grant_service=access_service,
        )
    )
    return client, grant_repository, redis, settings


def login_admin(client: TestClient):
    return client.post(
        "/api/v1/admin/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
    )


def grant_payload(project_ids: list[UUID]) -> dict[str, object]:
    return {
        "name": "  Fictional Company - Interview  ",
        "expires_at": (NOW + timedelta(days=7)).isoformat(),
        "max_requests": 100,
        "project_ids": [str(project_id) for project_id in project_ids],
    }


def create_grant(client: TestClient, project_ids: list[UUID]):
    return client.post(
        "/api/v1/admin/access-grants",
        json=grant_payload(project_ids),
    )


def test_admin_grant_endpoints_require_admin_cookie_and_reject_recruiter_cookie() -> None:
    client, repository, _redis, settings = make_client()
    project_id = next(iter(repository.projects))

    with client:
        missing = create_grant(client, [project_id])
        client.cookies.set(
            settings.recruiter_session_cookie_name,
            "random-recruiter-cookie",
            path="/api/v1",
        )
        recruiter_only = create_grant(client, [project_id])

    assert missing.status_code == 401
    assert recruiter_only.status_code == 401
    assert repository.records == {}


def test_admin_creates_grant_and_raw_token_is_returned_exactly_once() -> None:
    client, repository, _redis, _settings = make_client()
    project_ids = list(repository.projects)[:2]

    with client:
        assert login_admin(client).status_code == 200
        response = create_grant(client, [project_ids[0], project_ids[0], project_ids[1]])

    assert response.status_code == 201
    body = response.json()
    access_token = body["access_token"]
    assert access_token.startswith("rsg_")
    assert response.text.count(access_token) == 1
    assert "token_hash" not in response.text
    record = next(iter(repository.records.values()))
    assert record.token_hash == digest_access_token(access_token, PEPPER)
    assert [project.id for project in record.projects] == project_ids


def test_missing_project_rejects_entire_create_request() -> None:
    client, repository, _redis, _settings = make_client()

    with client:
        assert login_admin(client).status_code == 200
        response = create_grant(client, [next(iter(repository.projects)), uuid4()])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_project_scope"
    assert repository.records == {}


def test_admin_lists_gets_and_idempotently_revokes_safe_grant_metadata() -> None:
    client, repository, _redis, _settings = make_client()
    project_id = next(iter(repository.projects))

    with client:
        assert login_admin(client).status_code == 200
        first = create_grant(client, [project_id]).json()
        second = create_grant(client, [project_id]).json()
        listed = client.get("/api/v1/admin/access-grants")
        detail = client.get(f"/api/v1/admin/access-grants/{first['grant']['id']}")
        revoke_one = client.post(f"/api/v1/admin/access-grants/{first['grant']['id']}/revoke")
        revoke_two = client.post(f"/api/v1/admin/access-grants/{first['grant']['id']}/revoke")

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [
        second["grant"]["id"],
        first["grant"]["id"],
    ]
    assert detail.status_code == 200
    assert revoke_one.json()["revoked_at"] == revoke_two.json()["revoked_at"]
    for response in (listed, detail, revoke_one, revoke_two):
        assert "token_hash" not in response.text
        assert first["access_token"] not in response.text


def test_unknown_grant_detail_and_revoke_return_consistent_404() -> None:
    client, _repository, _redis, _settings = make_client()
    missing_id = uuid4()

    with client:
        assert login_admin(client).status_code == 200
        detail = client.get(f"/api/v1/admin/access-grants/{missing_id}")
        revoke = client.post(f"/api/v1/admin/access-grants/{missing_id}/revoke")

    assert detail.status_code == 404
    assert revoke.status_code == 404


def test_valid_exchange_sets_recruiter_cookie_and_me_returns_only_database_scope() -> None:
    client, repository, redis, settings = make_client()
    project_ids = list(repository.projects)[:2]

    with client:
        assert login_admin(client).status_code == 200
        created = create_grant(client, project_ids).json()
        access_token = created["access_token"]
        exchange = client.post(
            "/api/v1/access/exchange",
            json={"access_token": access_token},
        )
        recruiter_token = exchange.cookies.get(settings.recruiter_session_cookie_name)
        me = client.get("/api/v1/access/me")

    assert exchange.status_code == 200
    assert recruiter_token is not None
    assert recruiter_token not in exchange.text
    assert access_token not in exchange.text
    cookie = exchange.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/api/v1" in cookie
    assert "domain=" not in cookie
    session_key = next(key for key in redis.values if key.startswith("recruiter_session:"))
    assert recruiter_token not in session_key
    assert redis.ttls[session_key] <= settings.recruiter_session_ttl_seconds
    assert me.status_code == 200
    assert [project["id"] for project in me.json()["allowed_projects"]] == [
        str(value) for value in project_ids
    ]
    assert repository.records[UUID(created["grant"]["id"])].request_count == 0


@pytest.mark.parametrize("invalid_state", ["missing", "expired", "revoked", "exhausted", "empty"])
def test_invalid_grant_exchange_states_share_same_401(invalid_state: str) -> None:
    client, repository, _redis, _settings = make_client()
    project_id = next(iter(repository.projects))

    with client:
        assert login_admin(client).status_code == 200
        created = create_grant(client, [project_id]).json()
        grant_id = UUID(created["grant"]["id"])
        record = repository.records[grant_id]
        if invalid_state == "missing":
            repository.records.pop(grant_id)
        elif invalid_state == "expired":
            repository.records[grant_id] = replace(record, expires_at=NOW)
        elif invalid_state == "revoked":
            repository.records[grant_id] = replace(record, revoked_at=NOW)
        elif invalid_state == "exhausted":
            repository.records[grant_id] = replace(record, request_count=record.max_requests)
        else:
            repository.records[grant_id] = replace(record, projects=())
        response = client.post(
            "/api/v1/access/exchange",
            json={"access_token": created["access_token"]},
        )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "invalid_access_grant",
            "message": "The access grant is invalid or unavailable.",
        }
    }


def test_missing_random_and_admin_cookie_cannot_authenticate_recruiter() -> None:
    client, _repository, _redis, settings = make_client()

    with client:
        missing = client.get("/api/v1/access/me")
        assert login_admin(client).status_code == 200
        admin_only = client.get("/api/v1/access/me")
        client.cookies.set(
            settings.recruiter_session_cookie_name,
            "random-recruiter-cookie",
            path="/api/v1",
        )
        random_cookie = client.get("/api/v1/access/me")

    assert missing.status_code == 401
    assert admin_only.status_code == 401
    assert random_cookie.status_code == 401


def test_redis_snapshot_cannot_widen_scope_and_revoke_invalidates_old_cookie() -> None:
    client, repository, redis, _settings = make_client()
    allowed_id, unauthorized_id = list(repository.projects)[:2]

    with client:
        assert login_admin(client).status_code == 200
        created = create_grant(client, [allowed_id]).json()
        assert (
            client.post(
                "/api/v1/access/exchange",
                json={"access_token": created["access_token"]},
            ).status_code
            == 200
        )
        key = next(key for key in redis.values if key.startswith("recruiter_session:"))
        payload = json.loads(redis.values[key])
        payload["allowed_project_ids_snapshot"] = [str(unauthorized_id)]
        redis.values[key] = json.dumps(payload)
        before_revoke = client.get("/api/v1/access/me")
        revoke = client.post(f"/api/v1/admin/access-grants/{created['grant']['id']}/revoke")
        after_revoke = client.get("/api/v1/access/me")

    assert before_revoke.status_code == 200
    assert [item["id"] for item in before_revoke.json()["allowed_projects"]] == [str(allowed_id)]
    assert revoke.status_code == 200
    assert after_revoke.status_code == 401


def test_recruiter_logout_is_idempotent_invalidates_old_cookie_and_keeps_admin_session() -> None:
    client, repository, _redis, settings = make_client()
    project_id = next(iter(repository.projects))

    with client:
        assert login_admin(client).status_code == 200
        created = create_grant(client, [project_id]).json()
        exchange = client.post(
            "/api/v1/access/exchange",
            json={"access_token": created["access_token"]},
        )
        old_token = exchange.cookies.get(settings.recruiter_session_cookie_name)
        logout = client.post("/api/v1/access/logout")
        client.cookies.set(
            settings.recruiter_session_cookie_name,
            old_token,
            path="/api/v1",
        )
        old_cookie_me = client.get("/api/v1/access/me")
        admin_me = client.get("/api/v1/admin/auth/me")
        client.cookies.delete(settings.recruiter_session_cookie_name, path="/api/v1")
        second_logout = client.post("/api/v1/access/logout")

    assert logout.status_code == 204
    assert "max-age=0" in logout.headers["set-cookie"].lower()
    assert old_cookie_me.status_code == 401
    assert admin_me.status_code == 200
    assert second_logout.status_code == 204


def test_eleventh_failed_exchange_is_rate_limited_and_x_forwarded_for_is_ignored() -> None:
    client, _repository, redis, _settings = make_client()

    with client:
        for attempt in range(10):
            response = client.post(
                "/api/v1/access/exchange",
                json={"access_token": "malformed"},
                headers={"X-Forwarded-For": f"203.0.113.{attempt}"},
            )
            assert response.status_code == 401
        response = client.post(
            "/api/v1/access/exchange",
            json={"access_token": "malformed"},
            headers={"X-Forwarded-For": "198.51.100.8"},
        )

    assert response.status_code == 429
    keys = [key for key in redis.values if key.startswith("access_exchange_failures:")]
    assert len(keys) == 1
    assert redis.values[keys[0]] == "10"


@pytest.mark.parametrize("dependency", ["redis", "postgresql"])
def test_access_dependency_failures_return_sanitized_503(dependency: str) -> None:
    client, repository, redis, _settings = make_client()
    secret = "postgresql://admin:do-not-leak@database/resumegraph"
    if dependency == "redis":
        redis.unavailable = True
    else:
        repository.unavailable = True

    with client:
        response = client.post(
            "/api/v1/access/exchange",
            json={"access_token": "rsg_abcdefghijklmnopqrstuv"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert secret not in response.text
    assert "DependencyUnavailableError" not in response.text


def test_access_validation_and_logs_never_reflect_raw_tokens(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, repository, _redis, _settings = make_client()
    project_id = next(iter(repository.projects))
    validation_secret = "raw-token-that-must-not-be-reflected"

    with caplog.at_level("INFO"), client:
        assert login_admin(client).status_code == 200
        created = create_grant(client, [project_id]).json()
        access_token = created["access_token"]
        exchanged = client.post(
            "/api/v1/access/exchange",
            json={"access_token": access_token},
        )
        session_token = exchanged.cookies.get("resumegraph_recruiter_session")
        invalid = client.post(
            "/api/v1/access/exchange",
            json={"access_token": [validation_secret]},
        )

    assert invalid.status_code == 422
    assert validation_secret not in invalid.text
    assert access_token not in caplog.text
    assert session_token not in caplog.text
