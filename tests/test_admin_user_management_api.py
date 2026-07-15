from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.admin_auth import AdminPrincipal
from app.services.admin_auth import AdminUsernameExistsError
from app.services.admin_user_management import (
    CannotDeleteCurrentAdminError,
    LastAdminDeletionError,
    ManagedAdminNotFoundError,
)


@dataclass
class FakeHealthDependency:
    async def check_health(self) -> None:
        pass

    async def close(self) -> None:
        pass


class FakeAdminAuthService:
    def __init__(self, principal: AdminPrincipal) -> None:
        self.principal = principal

    async def get_current_admin(self, _session_token: str) -> AdminPrincipal:
        return self.principal


class FakeAdminManagementService:
    def __init__(self, current: AdminPrincipal) -> None:
        self.admins = [current, AdminPrincipal(id=uuid4(), username="reviewer")]
        self.create_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.deleted_id: UUID | None = None

    async def list_admins(self) -> list[AdminPrincipal]:
        return self.admins

    async def create_admin(self, username: str, _password: str) -> AdminPrincipal:
        if self.create_error is not None:
            raise self.create_error
        created = AdminPrincipal(id=uuid4(), username=username)
        self.admins.append(created)
        return created

    async def delete_admin(self, *, target_admin_id: UUID, current_admin_id: UUID) -> None:
        assert current_admin_id == self.admins[0].id
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted_id = target_admin_id


def make_client() -> tuple[TestClient, AdminPrincipal, FakeAdminManagementService, Settings]:
    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://resumegraph:local-only@postgres/resumegraph",
        redis_url="redis://redis:6379/0",
        cookie_secure=False,
        _env_file=None,
    )
    current = AdminPrincipal(id=uuid4(), username="admin")
    management = FakeAdminManagementService(current)
    client = TestClient(
        create_app(
            settings=settings,
            database=FakeHealthDependency(),
            redis=FakeHealthDependency(),
            admin_auth_service=FakeAdminAuthService(current),  # type: ignore[arg-type]
            admin_user_service=management,  # type: ignore[arg-type]
        )
    )
    return client, current, management, settings


def authenticate(client: TestClient, settings: Settings) -> None:
    client.cookies.set(
        settings.admin_session_cookie_name,
        "opaque-admin-session",
        path="/api/v1/admin",
    )


def test_admin_user_routes_require_admin_session() -> None:
    client, _current, _management, _settings = make_client()

    with client:
        response = client.get("/api/v1/admin/users")

    assert response.status_code == 401


def test_lists_and_creates_only_safe_admin_fields() -> None:
    client, current, _management, settings = make_client()

    with client:
        authenticate(client, settings)
        listed = client.get("/api/v1/admin/users")
        created = client.post(
            "/api/v1/admin/users",
            json={"username": " NewAdmin ", "password": "fictional password"},
        )

    assert listed.status_code == 200
    assert listed.json()[0] == {"id": str(current.id), "username": "admin"}
    assert created.status_code == 201
    assert created.json()["username"] == "newadmin"
    assert "password" not in created.text.lower()


def test_duplicate_username_returns_sanitized_conflict() -> None:
    client, _current, management, settings = make_client()
    management.create_error = AdminUsernameExistsError()

    with client:
        authenticate(client, settings)
        response = client.post(
            "/api/v1/admin/users",
            json={"username": "admin", "password": "fictional password"},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "admin_username_exists"


def test_delete_passes_authenticated_admin_identity() -> None:
    client, _current, management, settings = make_client()
    target_id = management.admins[1].id

    with client:
        authenticate(client, settings)
        response = client.delete(f"/api/v1/admin/users/{target_id}")

    assert response.status_code == 204
    assert management.deleted_id == target_id


def test_delete_conflicts_and_not_found_have_stable_codes() -> None:
    cases = [
        (CannotDeleteCurrentAdminError(), 409, "cannot_delete_current_admin"),
        (LastAdminDeletionError(), 409, "cannot_delete_last_admin"),
        (ManagedAdminNotFoundError(), 404, "admin_not_found"),
    ]
    for error, expected_status, expected_code in cases:
        client, _current, management, settings = make_client()
        management.delete_error = error
        with client:
            authenticate(client, settings)
            response = client.delete(f"/api/v1/admin/users/{uuid4()}")
        assert response.status_code == expected_status
        assert response.json()["error"]["code"] == expected_code


def test_invalid_password_is_not_reflected() -> None:
    client, _current, _management, settings = make_client()
    secret = "too-short"

    with client:
        authenticate(client, settings)
        response = client.post(
            "/api/v1/admin/users",
            json={"username": "new-admin", "password": secret},
        )

    assert response.status_code == 422
    assert secret not in response.text
