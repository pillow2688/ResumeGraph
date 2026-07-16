from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies.admin_auth import get_current_admin
from app.core.config import Settings
from app.main import create_app
from app.schemas.access_grant import (
    AccessGrantMetadata,
    ProjectSummary,
    RecruiterPrincipal,
)
from app.schemas.admin_auth import AdminPrincipal
from app.schemas.public_demo import PublicDemoAdminResponse, PublicDemoStatusResponse
from app.services.access_grant import RecruiterExchangeResult
from app.services.public_demo import (
    PublicDemoServiceUnavailableError,
    PublicDemoUnavailableError,
)

NOW = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)
GRANT_ID = uuid4()
PROJECT_ID = uuid4()


class FakeHealthDependency:
    async def check_health(self) -> None:
        pass

    async def close(self) -> None:
        pass


def grant_metadata() -> AccessGrantMetadata:
    return AccessGrantMetadata(
        id=GRANT_ID,
        name="Public Demo Grant",
        expires_at=NOW + timedelta(days=7),
        max_requests=100,
        request_count=10,
        revoked_at=None,
        created_at=NOW,
        projects=[ProjectSummary(id=PROJECT_ID, name="ResumeGraph")],
    )


def admin_response() -> PublicDemoAdminResponse:
    return PublicDemoAdminResponse(
        configured=True,
        candidate_name="马腾飞",
        default_access_grant_id=GRANT_ID,
        default_access_grant=grant_metadata(),
        enabled=True,
        created_at=NOW,
        updated_at=NOW,
    )


class FakePublicDemoService:
    def __init__(self) -> None:
        self.status = PublicDemoStatusResponse(available=True, candidate_name="马腾飞")
        self.admin = admin_response()
        self.session_unavailable = False
        self.service_unavailable = False
        self.update_kwargs: dict[str, object] | None = None

    async def get_public_status(self) -> PublicDemoStatusResponse:
        if self.service_unavailable:
            raise PublicDemoServiceUnavailableError
        return self.status

    async def create_public_session(self) -> RecruiterExchangeResult:
        if self.service_unavailable:
            raise PublicDemoServiceUnavailableError
        if self.session_unavailable:
            raise PublicDemoUnavailableError
        principal = RecruiterPrincipal(
            grant_id=GRANT_ID,
            grant_name="Public Demo Grant",
            allowed_project_ids=[PROJECT_ID],
            grant_expires_at=NOW + timedelta(days=7),
            remaining_requests=90,
            allowed_projects=[ProjectSummary(id=PROJECT_ID, name="ResumeGraph")],
        )
        return RecruiterExchangeResult(
            principal=principal,
            session_token="opaque-public-demo-session",
            ttl_seconds=3600,
            expires_at=NOW + timedelta(hours=1),
        )

    async def get_admin_config(self) -> PublicDemoAdminResponse:
        if self.service_unavailable:
            raise PublicDemoServiceUnavailableError
        return self.admin

    async def update_config(self, **kwargs: object) -> PublicDemoAdminResponse:
        self.update_kwargs = kwargs
        return self.admin


def make_client():
    settings = Settings(
        environment="test",
        cookie_secure=False,
        database_url="postgresql+asyncpg://test:test@postgres/test",
        redis_url="redis://redis:6379/0",
        access_token_pepper="fictional-public-demo-api-pepper",
        _env_file=None,
    )
    public_demo = FakePublicDemoService()
    app = create_app(
        settings=settings,
        database=FakeHealthDependency(),
        redis=FakeHealthDependency(),
        admin_auth_service=object(),
        access_grant_service=object(),
        project_service=object(),
        knowledge_document_service=object(),
        ingestion_service=object(),
        indexing_service=object(),
        publication_service=object(),
        deduplication_service=object(),
        knowledge_lifecycle_service=object(),
        interview_service=object(),
        interview_workflow_service=object(),
        public_demo_service=public_demo,
    )
    return app, TestClient(app), public_demo, settings


def test_public_status_returns_only_safe_demo_metadata() -> None:
    _app, client, _service, _settings = make_client()

    with client:
        response = client.get("/api/v1/public/demo")

    assert response.status_code == 200
    assert response.json() == {"available": True, "candidate_name": "马腾飞"}
    assert "grant" not in response.text.lower()
    assert "token" not in response.text.lower()
    assert "project" not in response.text.lower()


def test_public_status_returns_friendly_body_when_demo_is_closed() -> None:
    _app, client, service, _settings = make_client()
    service.status = PublicDemoStatusResponse(
        available=False,
        message="AI Interview 尚未开放",
    )

    with client:
        response = client.get("/api/v1/public/demo")

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "message": "AI Interview 尚未开放",
    }


def test_public_session_sets_httponly_cookie_without_exposing_grant_or_session() -> None:
    _app, client, _service, settings = make_client()

    with client:
        response = client.post("/api/v1/public/demo/session")

    assert response.status_code == 200
    assert response.json() == {"redirect_url": "/interview"}
    cookie = response.headers["set-cookie"].lower()
    assert settings.recruiter_session_cookie_name in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/api/v1" in cookie
    assert "opaque-public-demo-session" not in response.text
    assert str(GRANT_ID) not in response.text


def test_public_session_unavailable_and_dependency_failure_are_controlled() -> None:
    _app, client, service, _settings = make_client()

    with client:
        service.session_unavailable = True
        closed = client.post("/api/v1/public/demo/session")
        service.session_unavailable = False
        service.service_unavailable = True
        unavailable = client.post("/api/v1/public/demo/session")

    assert closed.status_code == 409
    assert closed.json()["error"] == {
        "code": "public_demo_unavailable",
        "message": "AI Interview 尚未开放",
    }
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "service_unavailable"


def test_admin_public_demo_requires_admin_and_updates_the_singleton() -> None:
    app, client, service, settings = make_client()

    async def current_admin() -> AdminPrincipal:
        return AdminPrincipal(id=uuid4(), username="admin")

    with client:
        client.cookies.set(
            settings.recruiter_session_cookie_name,
            "recruiter-only",
            path="/api/v1",
        )
        rejected = client.get("/api/v1/admin/public-demo")
        app.dependency_overrides[get_current_admin] = current_admin
        loaded = client.get("/api/v1/admin/public-demo")
        updated = client.put(
            "/api/v1/admin/public-demo",
            json={
                "candidate_name": "马腾飞",
                "default_access_grant_id": str(GRANT_ID),
                "enabled": True,
            },
        )

    assert rejected.status_code == 401
    assert loaded.status_code == 200
    assert loaded.json()["default_access_grant"]["projects"] == [
        {"id": str(PROJECT_ID), "name": "ResumeGraph"}
    ]
    assert updated.status_code == 200
    assert service.update_kwargs == {
        "candidate_name": "马腾飞",
        "default_access_grant_id": GRANT_ID,
        "enabled": True,
    }
