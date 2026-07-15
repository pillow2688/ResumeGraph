from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.admin_auth import AdminPrincipal
from app.schemas.ingestion import IngestionJobCreateResponse
from app.services.admin_auth import InvalidAdminSessionError
from app.services.indexing import (
    IndexingUnavailableError,
    IndexingVersionNotFoundError,
    IndexingVersionNotProcessableError,
)

ADMIN_ID = uuid4()
VERSION_ID = uuid4()
JOB_ID = uuid4()


class FakeHealthDependency:
    async def check_health(self) -> None:
        pass

    async def close(self) -> None:
        pass


class FakeAdminAuthService:
    async def get_current_admin(self, session_token: str) -> AdminPrincipal:
        if session_token != "valid-admin-session":
            raise InvalidAdminSessionError
        return AdminPrincipal(id=ADMIN_ID, username="admin")


class FakeIndexingService:
    def __init__(self) -> None:
        self.version_ids: list[UUID] = []
        self.failure: Exception | None = None

    async def create_job(self, version_id: UUID) -> IngestionJobCreateResponse:
        if self.failure is not None:
            raise self.failure
        self.version_ids.append(version_id)
        return IngestionJobCreateResponse(job_id=JOB_ID, status="pending")


def make_settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+asyncpg://resumegraph:local-only@postgres/resumegraph",
        redis_url="redis://redis:6379/0",
        access_token_pepper="fictional-indexing-api-pepper-safe",
        cookie_secure=False,
        _env_file=None,
    )


def make_client() -> tuple[TestClient, FakeIndexingService, Settings]:
    settings = make_settings()
    service = FakeIndexingService()
    app = create_app(
        settings=settings,
        database=FakeHealthDependency(),
        redis=FakeHealthDependency(),
        admin_auth_service=FakeAdminAuthService(),
        access_grant_service=object(),
        project_service=object(),
        knowledge_document_service=object(),
        ingestion_service=object(),
        indexing_service=service,
    )
    return TestClient(app), service, settings


def authenticate(client: TestClient, settings: Settings) -> None:
    client.cookies.set(
        settings.admin_session_cookie_name,
        "valid-admin-session",
        path="/api/v1/admin",
    )


def test_admin_can_start_single_knowledge_indexing_job_with_202() -> None:
    client, service, settings = make_client()

    with client:
        authenticate(client, settings)
        response = client.post(f"/api/v1/admin/document-versions/{VERSION_ID}/index")

    assert response.status_code == 202
    assert response.json() == {"job_id": str(JOB_ID), "status": "pending"}
    assert service.version_ids == [VERSION_ID]


def test_indexing_endpoint_requires_admin_and_rejects_recruiter_cookie() -> None:
    client, _service, settings = make_client()

    with client:
        response = client.post(f"/api/v1/admin/document-versions/{VERSION_ID}/index")
        client.cookies.set(
            settings.recruiter_session_cookie_name,
            "recruiter-only",
            path="/api/v1",
        )
        recruiter = client.post(f"/api/v1/admin/document-versions/{VERSION_ID}/index")

    assert response.status_code == 401
    assert recruiter.status_code == 401


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (IndexingVersionNotFoundError(), 404, "document_version_not_found"),
        (
            IndexingVersionNotProcessableError(),
            409,
            "document_version_not_processable",
        ),
        (IndexingUnavailableError(), 503, "service_unavailable"),
    ],
)
def test_indexing_start_errors_are_specific_and_sanitized(
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    client, service, settings = make_client()
    service.failure = error

    with client:
        authenticate(client, settings)
        response = client.post(f"/api/v1/admin/document-versions/{VERSION_ID}/index")

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert "Traceback" not in response.text
