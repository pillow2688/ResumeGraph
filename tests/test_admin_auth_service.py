import asyncio
import importlib
import importlib.util
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.security import hash_password
from app.infrastructure.admin_session import AdminSessionData
from app.infrastructure.health import DependencyUnavailableError
from app.models import AdminUser
from app.repositories.admin_user import AdminRepositoryUnavailableError


def load_service_module():
    assert importlib.util.find_spec("app.services") is not None, "service package must exist"
    name = "app.services.admin_auth"
    assert importlib.util.find_spec(name) is not None, f"{name} must exist"
    return importlib.import_module(name)


class FakeAdminRepository:
    def __init__(self, user: AdminUser | None = None) -> None:
        self.user = user
        self.created: AdminUser | None = None
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

    async def create(self, *, username: str, password_hash: str) -> AdminUser:
        if self.unavailable:
            raise AdminRepositoryUnavailableError
        self.created = AdminUser(id=uuid4(), username=username, password_hash=password_hash)
        self.user = self.created
        return self.created


class FakeSessionStore:
    def __init__(self) -> None:
        self.session: AdminSessionData | None = None
        self.created_token: str | None = None
        self.created_ttl: int | None = None
        self.deleted_token: str | None = None
        self.unavailable = False

    async def create(
        self,
        *,
        session_token: str,
        admin_id: UUID,
        username: str,
        ttl_seconds: int,
    ) -> AdminSessionData:
        if self.unavailable:
            raise DependencyUnavailableError("redis")
        now = datetime.now(UTC)
        self.created_token = session_token
        self.created_ttl = ttl_seconds
        self.session = AdminSessionData(
            admin_id=admin_id,
            username=username,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        return self.session

    async def read(self, _session_token: str) -> AdminSessionData | None:
        if self.unavailable:
            raise DependencyUnavailableError("redis")
        return self.session

    async def delete(self, session_token: str) -> None:
        if self.unavailable:
            raise DependencyUnavailableError("redis")
        self.deleted_token = session_token
        self.session = None


class FakeLoginLimiter:
    def __init__(self) -> None:
        self.count = 0
        self.cleared = False
        self.unavailable = False

    async def is_limited(self, _username: str, _client_host: str) -> bool:
        if self.unavailable:
            raise DependencyUnavailableError("redis")
        return self.count >= 5

    async def record_failure(self, _username: str, _client_host: str) -> int:
        if self.unavailable:
            raise DependencyUnavailableError("redis")
        self.count += 1
        return self.count

    async def clear(self, _username: str, _client_host: str) -> None:
        if self.unavailable:
            raise DependencyUnavailableError("redis")
        self.cleared = True
        self.count = 0


def make_service(
    repository: FakeAdminRepository,
    store: FakeSessionStore | None = None,
    limiter: FakeLoginLimiter | None = None,
):
    service_module = load_service_module()
    return service_module.AdminAuthService(
        repository,
        store or FakeSessionStore(),
        limiter or FakeLoginLimiter(),
        session_ttl_seconds=3600,
        login_max_failures=5,
    )


def test_create_admin_normalizes_username_and_stores_only_argon2_hash() -> None:
    repository = FakeAdminRepository()
    service = make_service(repository)
    password = "correct horse battery staple"

    principal = asyncio.run(service.create_admin("  Admin  ", password))

    assert principal.username == "admin"
    assert repository.created is not None
    assert repository.created.username == "admin"
    assert repository.created.password_hash.startswith("$argon2")
    assert password not in repository.created.password_hash
    assert not hasattr(repository.created, "password")


def test_create_admin_rejects_existing_normalized_username() -> None:
    service_module = load_service_module()
    existing = AdminUser(id=uuid4(), username="admin", password_hash="hash")
    service = make_service(FakeAdminRepository(existing))

    with pytest.raises(service_module.AdminUsernameExistsError):
        asyncio.run(service.create_admin(" ADMIN ", "correct horse battery staple"))


def test_login_success_creates_fixed_ttl_session_and_clears_failures() -> None:
    password = "correct horse battery staple"
    admin = AdminUser(id=uuid4(), username="admin", password_hash=hash_password(password))
    store = FakeSessionStore()
    limiter = FakeLoginLimiter()
    service = make_service(FakeAdminRepository(admin), store, limiter)

    result = asyncio.run(service.login(" ADMIN ", password, "127.0.0.1"))

    assert result.principal.id == admin.id
    assert result.principal.username == "admin"
    assert result.session_token == store.created_token
    assert len(result.session_token) >= 43
    assert store.created_ttl == 3600
    assert limiter.cleared is True


@pytest.mark.parametrize("admin_exists", [True, False])
def test_wrong_password_and_missing_username_have_same_error(admin_exists: bool) -> None:
    service_module = load_service_module()
    admin = None
    if admin_exists:
        admin = AdminUser(
            id=uuid4(),
            username="admin",
            password_hash=hash_password("correct horse battery staple"),
        )
    limiter = FakeLoginLimiter()
    service = make_service(FakeAdminRepository(admin), limiter=limiter)

    with pytest.raises(service_module.InvalidCredentialsError):
        asyncio.run(service.login("admin", "wrong password", "127.0.0.1"))

    assert limiter.count == 1


def test_fifth_failed_login_is_rate_limited() -> None:
    service_module = load_service_module()
    limiter = FakeLoginLimiter()
    limiter.count = 4
    service = make_service(FakeAdminRepository(), limiter=limiter)

    with pytest.raises(service_module.AdminLoginRateLimitedError):
        asyncio.run(service.login("admin", "wrong password", "127.0.0.1"))

    assert limiter.count == 5


def test_current_admin_uses_postgresql_identity_not_redis_username() -> None:
    admin = AdminUser(id=uuid4(), username="database-admin", password_hash="hash")
    store = FakeSessionStore()
    now = datetime.now(UTC)
    store.session = AdminSessionData(
        admin_id=admin.id,
        username="untrusted-redis-name",
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    service = make_service(FakeAdminRepository(admin), store)

    principal = asyncio.run(service.get_current_admin("opaque-token"))

    assert principal.username == "database-admin"


@pytest.mark.parametrize("session_exists,admin_exists", [(False, True), (True, False)])
def test_invalid_session_or_deleted_admin_is_rejected(
    session_exists: bool,
    admin_exists: bool,
) -> None:
    service_module = load_service_module()
    admin_id = uuid4()
    admin = AdminUser(id=admin_id, username="admin", password_hash="hash") if admin_exists else None
    store = FakeSessionStore()
    if session_exists:
        now = datetime.now(UTC)
        store.session = AdminSessionData(
            admin_id=admin_id,
            username="admin",
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
    service = make_service(FakeAdminRepository(admin), store)

    with pytest.raises(service_module.InvalidAdminSessionError):
        asyncio.run(service.get_current_admin("opaque-token"))


def test_logout_deletes_server_side_session() -> None:
    store = FakeSessionStore()
    service = make_service(FakeAdminRepository(), store)

    asyncio.run(service.logout("opaque-token"))

    assert store.deleted_token == "opaque-token"


@pytest.mark.parametrize("failure_source", ["repository", "session", "limiter"])
def test_infrastructure_failures_are_translated_to_safe_service_error(
    failure_source: str,
) -> None:
    service_module = load_service_module()
    repository = FakeAdminRepository()
    store = FakeSessionStore()
    limiter = FakeLoginLimiter()
    if failure_source == "repository":
        repository.unavailable = True
    elif failure_source == "session":
        store.unavailable = True
    else:
        limiter.unavailable = True
    admin = AdminUser(
        id=uuid4(),
        username="admin",
        password_hash=hash_password("correct horse battery staple"),
    )
    if not repository.unavailable:
        repository.user = admin
    service = make_service(repository, store, limiter)

    with pytest.raises(service_module.AdminAuthUnavailableError) as raised:
        asyncio.run(service.login("admin", "correct horse battery staple", "127.0.0.1"))

    assert "redis" not in str(raised.value).lower()
    assert "postgresql" not in str(raised.value).lower()


@pytest.mark.parametrize("password", ["short", "x" * 129])
def test_unknown_username_still_pays_dummy_argon2_verification_cost(
    monkeypatch: pytest.MonkeyPatch,
    password: str,
) -> None:
    service_module = load_service_module()
    verification_calls: list[tuple[str, str]] = []

    def record_verification(received_password: str, password_hash: str) -> bool:
        verification_calls.append((received_password, password_hash))
        return False

    monkeypatch.setattr(service_module, "verify_password", record_verification)
    service = make_service(FakeAdminRepository())

    with pytest.raises(service_module.InvalidCredentialsError):
        asyncio.run(service.login("missing", password, "127.0.0.1"))

    assert verification_calls == [(password, service_module.DUMMY_ADMIN_PASSWORD_HASH)]


def test_hanging_auth_dependency_times_out_as_sanitized_unavailable_error() -> None:
    service_module = load_service_module()

    class HangingLimiter(FakeLoginLimiter):
        async def is_limited(self, _username: str, _client_host: str) -> bool:
            await asyncio.Event().wait()
            return False

    service = service_module.AdminAuthService(
        FakeAdminRepository(),
        FakeSessionStore(),
        HangingLimiter(),
        session_ttl_seconds=3600,
        login_max_failures=5,
        dependency_timeout_seconds=0.01,
    )

    with pytest.raises(service_module.AdminAuthUnavailableError) as raised:
        asyncio.run(service.login("admin", "fictional password", "127.0.0.1"))

    assert "timeout" not in str(raised.value).lower()
