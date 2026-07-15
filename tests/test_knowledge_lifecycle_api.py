from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.admin_auth import AdminPrincipal
from app.services.admin_auth import InvalidAdminSessionError
from app.services.knowledge_lifecycle import (
    ActiveDocumentJobError,
    DocumentConfirmationError,
    KnowledgeDocumentNotFoundError,
    KnowledgeLifecycleUnavailableError,
    VersionNotDeletableError,
    VersionNotFoundError,
)

ADMIN_ID = uuid4()


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


class FakeKnowledgeLifecycleService:
    def __init__(self) -> None:
        self.failure: Exception | None = None
        self.version_calls: list[UUID] = []
        self.document_calls: list[tuple[UUID, str]] = []

    async def delete_version(self, version_id: UUID) -> None:
        if self.failure is not None:
            raise self.failure
        self.version_calls.append(version_id)

    async def delete_document(self, document_id: UUID, *, confirmation: str) -> None:
        if self.failure is not None:
            raise self.failure
        self.document_calls.append((document_id, confirmation))


def make_client() -> tuple[TestClient, FakeKnowledgeLifecycleService, Settings]:
    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://resumegraph:local-only@postgres/resumegraph",
        redis_url="redis://redis:6379/0",
        access_token_pepper="fictional-lifecycle-api-pepper-safe",
        cookie_secure=False,
        _env_file=None,
    )
    service = FakeKnowledgeLifecycleService()
    app = create_app(
        settings=settings,
        database=FakeHealthDependency(),
        redis=FakeHealthDependency(),
        admin_auth_service=FakeAdminAuthService(),
        access_grant_service=object(),
        project_service=object(),
        knowledge_document_service=object(),
        ingestion_service=object(),
        indexing_service=object(),
        publication_service=object(),
        knowledge_lifecycle_service=service,
    )
    return TestClient(app), service, settings


def authenticate(client: TestClient, settings: Settings) -> None:
    client.cookies.set(
        settings.admin_session_cookie_name,
        "valid-admin-session",
        path="/api/v1/admin",
    )


def test_admin_can_delete_safe_version_and_permanently_delete_confirmed_document() -> None:
    client, service, settings = make_client()
    version_id = uuid4()
    document_id = uuid4()

    with client:
        anonymous = client.delete(f"/api/v1/admin/document-versions/{version_id}")
        authenticate(client, settings)
        version_response = client.delete(f"/api/v1/admin/document-versions/{version_id}")
        document_response = client.request(
            "DELETE",
            f"/api/v1/admin/documents/{document_id}",
            json={"confirmation_title": "Fictional resume"},
        )

    assert anonymous.status_code == 401
    assert version_response.status_code == 204
    assert version_response.content == b""
    assert document_response.status_code == 204
    assert service.version_calls == [version_id]
    assert service.document_calls == [(document_id, "Fictional resume")]


@pytest.mark.parametrize(
    ("failure", "path_kind", "status_code", "code"),
    [
        (VersionNotFoundError(), "version", 404, "document_version_not_found"),
        (KnowledgeDocumentNotFoundError(), "document", 404, "document_not_found"),
        (VersionNotDeletableError(), "version", 409, "document_version_not_deletable"),
        (ActiveDocumentJobError(), "document", 409, "active_document_job"),
        (DocumentConfirmationError(), "document", 409, "document_confirmation_mismatch"),
        (KnowledgeLifecycleUnavailableError(), "document", 503, "service_unavailable"),
    ],
)
def test_lifecycle_api_returns_sanitized_errors(
    failure: Exception,
    path_kind: str,
    status_code: int,
    code: str,
) -> None:
    client, service, settings = make_client()
    service.failure = failure
    resource_id = uuid4()

    with client:
        authenticate(client, settings)
        if path_kind == "version":
            response = client.delete(f"/api/v1/admin/document-versions/{resource_id}")
        else:
            response = client.request(
                "DELETE",
                f"/api/v1/admin/documents/{resource_id}",
                json={"confirmation_title": "Fictional resume"},
            )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert "Fictional resume" not in response.text
    assert "Traceback" not in response.text
