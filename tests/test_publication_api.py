from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.repositories.ingestion import DocumentChunkRecord
from app.schemas.admin_auth import AdminPrincipal
from app.schemas.ingestion import DocumentChunkResponse
from app.schemas.publication import PublicationState
from app.services.admin_auth import InvalidAdminSessionError
from app.services.publication import (
    ChunkNotEditableError,
    ChunkNotFoundError,
    DocumentNotFoundError,
    PublicationIntegrityError,
    PublicationUnavailableError,
    VersionNotFoundError,
    VersionNotPublishableError,
)

ADMIN_ID = uuid4()
CHUNK_ID = uuid4()
NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


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


class FakePublicationService:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, bool]] = []
        self.failure: Exception | None = None
        self.publish_calls: list[UUID] = []
        self.unpublish_calls: list[UUID] = []

    async def set_chunk_enabled(self, chunk_id: UUID, *, enabled: bool):
        if self.failure is not None:
            raise self.failure
        self.calls.append((chunk_id, enabled))
        record = DocumentChunkRecord(
            id=chunk_id,
            document_version_id=uuid4(),
            chunk_index=0,
            heading_path=("Architecture",),
            content="A bounded retry design.",
            content_hash="a" * 64,
            character_count=23,
            enabled=enabled,
            created_at=NOW,
            extracted_metadata={},
        )
        return DocumentChunkResponse(**record.__dict__)

    async def publish_version(self, version_id: UUID):
        if self.failure is not None:
            raise self.failure
        self.publish_calls.append(version_id)
        return PublicationState(
            document_id=uuid4(),
            current_published_version_id=version_id,
        )

    async def unpublish_document(self, document_id: UUID):
        if self.failure is not None:
            raise self.failure
        self.unpublish_calls.append(document_id)
        return PublicationState(
            document_id=document_id,
            current_published_version_id=None,
        )


def make_settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+asyncpg://resumegraph:local-only@postgres/resumegraph",
        redis_url="redis://redis:6379/0",
        access_token_pepper="fictional-publication-api-pepper-safe",
        cookie_secure=False,
        embedding_provider_name="zhipu",
        embedding_base_url="https://open.bigmodel.cn/api/paas/v4",
        embedding_api_key="test-only-secret-key",
        embedding_model="embedding-3",
        embedding_dimensions=1024,
        embedding_send_dimensions=True,
        embedding_batch_size=10,
        embedding_timeout_seconds=30,
        embedding_max_retries=2,
        _env_file=None,
    )


def make_client():
    settings = make_settings()
    service = FakePublicationService()
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
        publication_service=service,
    )
    return TestClient(app), service, settings


def authenticate(client: TestClient, settings: Settings) -> None:
    client.cookies.set(
        settings.admin_session_cookie_name,
        "valid-admin-session",
        path="/api/v1/admin",
    )


def test_admin_can_view_generic_embedding_configuration_without_secret() -> None:
    client, _service, settings = make_client()

    with client:
        authenticate(client, settings)
        response = client.get("/api/v1/admin/embedding-config")

    assert response.status_code == 200
    assert response.json() == {
        "provider_name": "zhipu",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "embedding-3",
        "dimensions": 1024,
        "send_dimensions": True,
        "batch_size": 10,
        "timeout_seconds": 30.0,
        "max_retries": 2,
    }
    assert "test-only-secret-key" not in response.text
    assert "api_key" not in response.text


def test_admin_can_toggle_chunk_and_anonymous_user_cannot() -> None:
    client, service, settings = make_client()

    with client:
        anonymous = client.patch(
            f"/api/v1/admin/document-chunks/{CHUNK_ID}",
            json={"enabled": False},
        )
        authenticate(client, settings)
        response = client.patch(
            f"/api/v1/admin/document-chunks/{CHUNK_ID}",
            json={"enabled": False},
        )

    assert anonymous.status_code == 401
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert service.calls == [(CHUNK_ID, False)]


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (ChunkNotFoundError(), 404, "document_chunk_not_found"),
        (ChunkNotEditableError(), 409, "document_chunk_not_editable"),
        (PublicationUnavailableError(), 503, "service_unavailable"),
    ],
)
def test_chunk_toggle_returns_sanitized_errors(error, status_code: int, code: str) -> None:
    client, service, settings = make_client()
    service.failure = error

    with client:
        authenticate(client, settings)
        response = client.patch(
            f"/api/v1/admin/document-chunks/{CHUNK_ID}",
            json={"enabled": True},
        )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert "test-only-secret-key" not in response.text


def test_admin_can_publish_and_unpublish_without_vendor_specific_routes() -> None:
    client, service, settings = make_client()
    version_id = uuid4()
    document_id = uuid4()

    with client:
        authenticate(client, settings)
        published = client.post(f"/api/v1/admin/document-versions/{version_id}/publish")
        unpublished = client.delete(f"/api/v1/admin/documents/{document_id}/publication")

    assert published.status_code == 200
    assert published.json()["current_published_version_id"] == str(version_id)
    assert unpublished.status_code == 200
    assert unpublished.json() == {
        "document_id": str(document_id),
        "current_published_version_id": None,
    }
    assert service.publish_calls == [version_id]
    assert service.unpublish_calls == [document_id]


@pytest.mark.parametrize(
    ("method", "error", "status_code", "code"),
    [
        ("publish", VersionNotFoundError(), 404, "document_version_not_found"),
        ("publish", VersionNotPublishableError(), 409, "document_version_not_publishable"),
        ("publish", PublicationIntegrityError(), 409, "publication_integrity_failed"),
        ("unpublish", DocumentNotFoundError(), 404, "document_not_found"),
        ("unpublish", PublicationUnavailableError(), 503, "service_unavailable"),
    ],
)
def test_publication_api_returns_safe_errors(method, error, status_code: int, code: str) -> None:
    client, service, settings = make_client()
    service.failure = error

    with client:
        authenticate(client, settings)
        if method == "publish":
            response = client.post(f"/api/v1/admin/document-versions/{uuid4()}/publish")
        else:
            response = client.delete(f"/api/v1/admin/documents/{uuid4()}/publication")

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert "test-only-secret-key" not in response.text
