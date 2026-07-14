import inspect
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import hash_password
from app.infrastructure.admin_login_limiter import AdminLoginRateLimiter
from app.infrastructure.admin_session import AdminSessionStore
from app.infrastructure.health import DependencyUnavailableError
from app.main import create_app
from app.models import AdminUser
from app.repositories.admin_user import AdminRepositoryUnavailableError
from app.services.admin_auth import AdminAuthService

TEST_PASSWORD = "fictional password for tests"
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


@dataclass
class FakeHealthDependency:
    async def check_health(self) -> None:
        pass

    async def close(self) -> None:
        pass


class InMemoryAdminRepository:
    def __init__(self, user: AdminUser | None) -> None:
        self.user = user
        self.unavailable = False

    async def get_by_username(self, username: str) -> AdminUser | None:
        if self.unavailable:
            raise AdminRepositoryUnavailableError
        if self.user is not None and self.user.username == username:
            return self.user
        return None

    async def get_by_id(self, admin_id: UUID) -> AdminUser | None:
        if self.unavailable:
            raise AdminRepositoryUnavailableError
        if self.user is not None and self.user.id == admin_id:
            return self.user
        return None


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


def make_settings(*, cookie_secure: bool = False) -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+asyncpg://resumegraph:local-only@postgres/resumegraph",
        redis_url="redis://redis:6379/0",
        admin_session_ttl_seconds=3600,
        cookie_secure=cookie_secure,
        admin_login_max_failures=5,
        admin_login_window_seconds=300,
        _env_file=None,
    )


def make_client(
    *,
    user_exists: bool = True,
    cookie_secure: bool = False,
) -> tuple[TestClient, InMemoryAdminRepository, InMemoryRedis, Settings]:
    assert "admin_auth_service" in inspect.signature(create_app).parameters
    settings = make_settings(cookie_secure=cookie_secure)
    user = None
    if user_exists:
        user = AdminUser(id=uuid4(), username="admin", password_hash=TEST_PASSWORD_HASH)
    repository = InMemoryAdminRepository(user)
    redis = InMemoryRedis()
    service = AdminAuthService(
        repository,
        AdminSessionStore(redis),
        AdminLoginRateLimiter(
            redis,
            max_failures=settings.admin_login_max_failures,
            window_seconds=settings.admin_login_window_seconds,
        ),
        session_ttl_seconds=settings.admin_session_ttl_seconds,
        login_max_failures=settings.admin_login_max_failures,
    )
    client = TestClient(
        create_app(
            settings=settings,
            database=FakeHealthDependency(),
            redis=FakeHealthDependency(),
            admin_auth_service=service,
        )
    )
    return client, repository, redis, settings


def login(client: TestClient, *, username: str = "admin", password: str = TEST_PASSWORD):
    return client.post(
        "/api/v1/admin/auth/login",
        json={"username": username, "password": password},
    )


def test_login_returns_safe_admin_and_sets_scoped_http_only_cookie() -> None:
    client, repository, redis, settings = make_client()

    with client:
        response = login(client, username=" ADMIN ")

    assert response.status_code == 200
    assert response.json() == {"admin": {"id": str(repository.user.id), "username": "admin"}}
    set_cookie = response.headers["set-cookie"].lower()
    assert f"{settings.admin_session_cookie_name}=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/api/v1/admin" in set_cookie
    assert "max-age=3600" in set_cookie
    assert "domain=" not in set_cookie
    session_token = response.cookies.get(settings.admin_session_cookie_name)
    assert session_token is not None
    assert session_token not in response.text
    assert repository.user.password_hash not in response.text
    assert not hasattr(repository.user, "password")
    session_key = next(key for key in redis.values if key.startswith("admin_session:"))
    assert session_token not in session_key
    assert session_token not in redis.values[session_key]
    assert redis.ttls[session_key] == settings.admin_session_ttl_seconds


def test_secure_cookie_flag_is_configurable() -> None:
    client, _repository, _redis, _settings = make_client(cookie_secure=True)

    with client:
        response = login(client)

    assert "secure" in response.headers["set-cookie"].lower()


def test_valid_cookie_can_access_me() -> None:
    client, repository, _redis, _settings = make_client()

    with client:
        assert login(client).status_code == 200
        response = client.get("/api/v1/admin/auth/me")

    assert response.status_code == 200
    assert response.json() == {"id": str(repository.user.id), "username": "admin"}


@pytest.mark.parametrize("cookie_value", [None, "random-opaque-cookie"])
def test_missing_or_random_cookie_cannot_access_me(cookie_value: str | None) -> None:
    client, _repository, _redis, settings = make_client()

    with client:
        if cookie_value is not None:
            client.cookies.set(
                settings.admin_session_cookie_name,
                cookie_value,
                path="/api/v1/admin",
            )
        response = client.get("/api/v1/admin/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_expired_redis_session_cannot_access_me() -> None:
    client, _repository, redis, _settings = make_client()

    with client:
        assert login(client).status_code == 200
        session_key = next(key for key in redis.values if key.startswith("admin_session:"))
        redis.values.pop(session_key)
        response = client.get("/api/v1/admin/auth/me")

    assert response.status_code == 401


def test_redis_session_does_not_survive_deleted_postgresql_admin() -> None:
    client, repository, _redis, _settings = make_client()

    with client:
        assert login(client).status_code == 200
        repository.user = None
        response = client.get("/api/v1/admin/auth/me")

    assert response.status_code == 401


@pytest.mark.parametrize("user_exists", [True, False])
def test_wrong_password_and_unknown_username_share_invalid_credentials_response(
    user_exists: bool,
) -> None:
    client, _repository, _redis, _settings = make_client(user_exists=user_exists)

    with client:
        response = login(client, password="wrong fictional password")

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "invalid_credentials",
            "message": "Invalid administrator credentials.",
        }
    }


def test_fifth_failed_login_is_rate_limited_and_x_forwarded_for_is_ignored() -> None:
    client, _repository, redis, _settings = make_client(user_exists=False)

    with client:
        for attempt in range(4):
            response = client.post(
                "/api/v1/admin/auth/login",
                json={"username": "admin", "password": "wrong fictional password"},
                headers={"X-Forwarded-For": f"203.0.113.{attempt}"},
            )
            assert response.status_code == 401
        response = client.post(
            "/api/v1/admin/auth/login",
            json={"username": "admin", "password": "wrong fictional password"},
            headers={"X-Forwarded-For": "198.51.100.8"},
        )

    assert response.status_code == 429
    failure_keys = [key for key in redis.values if key.startswith("admin_login_failures:")]
    assert len(failure_keys) == 1
    assert redis.values[failure_keys[0]] == "5"


def test_successful_login_clears_failure_counter() -> None:
    client, _repository, redis, _settings = make_client()

    with client:
        assert login(client, password="wrong fictional password").status_code == 401
        assert any(key.startswith("admin_login_failures:") for key in redis.values)
        assert login(client).status_code == 200

    assert not any(key.startswith("admin_login_failures:") for key in redis.values)


def test_logout_is_idempotent_and_invalidates_old_cookie() -> None:
    client, _repository, _redis, settings = make_client()

    with client:
        login_response = login(client)
        old_token = login_response.cookies.get(settings.admin_session_cookie_name)
        logout_response = client.post("/api/v1/admin/auth/logout")
        assert logout_response.status_code == 204
        assert "max-age=0" in logout_response.headers["set-cookie"].lower()
        client.cookies.set(
            settings.admin_session_cookie_name,
            old_token,
            path="/api/v1/admin",
        )
        me_response = client.get("/api/v1/admin/auth/me")
        client.cookies.clear()
        second_logout = client.post("/api/v1/admin/auth/logout")

    assert me_response.status_code == 401
    assert second_logout.status_code == 204


@pytest.mark.parametrize("dependency", ["redis", "postgresql"])
def test_dependency_failure_returns_sanitized_503(dependency: str) -> None:
    client, repository, redis, _settings = make_client()
    if dependency == "redis":
        redis.unavailable = True
    else:
        repository.unavailable = True
    secret = "postgresql://admin:do-not-leak@database/resumegraph"

    with client:
        response = login(client)

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "service_unavailable",
            "message": "Administrator authentication is temporarily unavailable.",
        }
    }
    assert secret not in response.text
    assert "DependencyUnavailableError" not in response.text


def test_login_validation_error_does_not_echo_password_input() -> None:
    client, _repository, _redis, _settings = make_client()
    secret = "credential-that-must-not-be-reflected"

    with client:
        response = client.post(
            "/api/v1/admin/auth/login",
            json={"username": "admin", "password": [secret]},
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_request",
            "message": "Request validation failed.",
        }
    }
    assert secret not in response.text


def test_login_openapi_documents_sanitized_validation_error_shape() -> None:
    client, _repository, _redis, _settings = make_client()

    with client:
        response = client.get("/openapi.json")

    validation_response = response.json()["paths"]["/api/v1/admin/auth/login"]["post"]["responses"][
        "422"
    ]
    assert validation_response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }


def test_authentication_logs_do_not_contain_credentials_hash_or_session_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, repository, _redis, settings = make_client()

    with caplog.at_level("INFO"), client:
        response = login(client)
        session_token = response.cookies.get(settings.admin_session_cookie_name)
        assert session_token is not None
        client.post("/api/v1/admin/auth/logout")

    assert TEST_PASSWORD not in caplog.text
    assert repository.user.password_hash not in caplog.text
    assert session_token not in caplog.text
