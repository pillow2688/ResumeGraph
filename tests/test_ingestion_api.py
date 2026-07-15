from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.admin_auth import AdminPrincipal
from app.schemas.ingestion import (
    DocumentChunkResponse,
    IngestionJobCreateResponse,
    IngestionJobDetail,
)
from app.services.admin_auth import InvalidAdminSessionError
from app.services.ingestion import (
    DocumentVersionNotProcessableError,
    IngestionJobNotFoundError,
    IngestionUnavailableError,
    IngestionVersionNotFoundError,
)

NOW = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
ADMIN_ID = uuid4()
VERSION_ID = uuid4()
DOCUMENT_ID = uuid4()
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


class FakeIngestionService:
    def __init__(self) -> None:
        self.failure: Exception | None = None
        self.last_call: tuple[str, UUID] | None = None

    def _check(self) -> None:
        if self.failure is not None:
            raise self.failure

    async def create_job(self, version_id: UUID) -> IngestionJobCreateResponse:
        self._check()
        self.last_call = ("create", version_id)
        return IngestionJobCreateResponse(job_id=JOB_ID, status="pending")

    async def get_job(self, job_id: UUID) -> IngestionJobDetail:
        self._check()
        self.last_call = ("job", job_id)
        return IngestionJobDetail(
            job_id=JOB_ID,
            document_version_id=VERSION_ID,
            document_id=DOCUMENT_ID,
            document_title="Architecture",
            version_number=2,
            status="processing",
            stage="chunking",
            progress=55,
            error_message=None,
            created_at=NOW,
            started_at=NOW,
            finished_at=None,
        )

    async def list_chunks(self, version_id: UUID) -> list[DocumentChunkResponse]:
        self._check()
        self.last_call = ("chunks", version_id)
        return [
            DocumentChunkResponse(
                id=uuid4(),
                document_version_id=VERSION_ID,
                chunk_index=0,
                heading_path=("Architecture", "Worker"),
                content="### Worker\n\nContent",
                content_hash="a" * 64,
                character_count=20,
                enabled=True,
                created_at=NOW,
            )
        ]


def make_settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+asyncpg://resumegraph:local-only@postgres/resumegraph",
        redis_url="redis://redis:6379/0",
        access_token_pepper="fictional-ingestion-api-pepper-safe",
        cookie_secure=False,
        _env_file=None,
    )


def make_client() -> tuple[TestClient, FakeIngestionService, Settings]:
    settings = make_settings()
    service = FakeIngestionService()
    app = create_app(
        settings=settings,
        database=FakeHealthDependency(),
        redis=FakeHealthDependency(),
        admin_auth_service=FakeAdminAuthService(),
        access_grant_service=object(),
        project_service=object(),
        knowledge_document_service=object(),
        ingestion_service=service,
    )
    return TestClient(app), service, settings


def authenticate(client: TestClient, settings: Settings) -> None:
    client.cookies.set(
        settings.admin_session_cookie_name,
        "valid-admin-session",
        path="/api/v1/admin",
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", f"/api/v1/admin/document-versions/{VERSION_ID}/process"),
        ("get", f"/api/v1/admin/jobs/{JOB_ID}"),
        ("get", f"/api/v1/admin/document-versions/{VERSION_ID}/chunks"),
    ],
)
def test_ingestion_routes_require_admin_and_reject_recruiter_cookie(method: str, path: str) -> None:
    client, _service, settings = make_client()

    with client:
        unauthenticated = client.request(method, path)
        client.cookies.set(
            settings.recruiter_session_cookie_name,
            "recruiter-only",
            path="/api/v1",
        )
        recruiter = client.request(method, path)

    assert unauthenticated.status_code == 401
    assert recruiter.status_code == 401
    assert recruiter.json()["error"]["code"] == "authentication_required"


def test_admin_creates_job_with_202_and_reads_postgresql_status() -> None:
    client, service, settings = make_client()

    with client:
        authenticate(client, settings)
        created = client.post(f"/api/v1/admin/document-versions/{VERSION_ID}/process")
        detail = client.get(f"/api/v1/admin/jobs/{JOB_ID}")

    assert created.status_code == 202
    assert created.json() == {"job_id": str(JOB_ID), "status": "pending"}
    assert detail.status_code == 200
    assert detail.json()["document_title"] == "Architecture"
    assert detail.json()["status"] == "processing"
    assert detail.json()["stage"] == "chunking"
    assert detail.json()["progress"] == 55
    assert service.last_call == ("job", JOB_ID)


def test_admin_reads_chunks_in_stable_order_shape() -> None:
    client, _service, settings = make_client()

    with client:
        authenticate(client, settings)
        response = client.get(f"/api/v1/admin/document-versions/{VERSION_ID}/chunks")

    assert response.status_code == 200
    assert response.json()[0]["chunk_index"] == 0
    assert response.json()[0]["heading_path"] == ["Architecture", "Worker"]
    assert response.json()[0]["content"] == "### Worker\n\nContent"


@pytest.mark.parametrize(
    ("error", "method", "path", "status_code", "code"),
    [
        (
            IngestionVersionNotFoundError(),
            "post",
            f"/api/v1/admin/document-versions/{VERSION_ID}/process",
            404,
            "document_version_not_found",
        ),
        (
            IngestionJobNotFoundError(),
            "get",
            f"/api/v1/admin/jobs/{JOB_ID}",
            404,
            "ingestion_job_not_found",
        ),
        (
            DocumentVersionNotProcessableError(),
            "post",
            f"/api/v1/admin/document-versions/{VERSION_ID}/process",
            409,
            "document_version_not_processable",
        ),
        (
            IngestionUnavailableError(),
            "get",
            f"/api/v1/admin/jobs/{JOB_ID}",
            503,
            "service_unavailable",
        ),
    ],
)
def test_ingestion_errors_are_specific_and_database_details_are_sanitized(
    error: Exception,
    method: str,
    path: str,
    status_code: int,
    code: str,
) -> None:
    client, service, settings = make_client()
    service.failure = error

    with client:
        authenticate(client, settings)
        response = client.request(method, path)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert "postgresql://" not in response.text
    assert "Traceback" not in response.text
