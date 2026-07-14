from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.admin_auth import AdminPrincipal
from app.schemas.knowledge_document import (
    DocumentProjectSummary,
    DocumentVersion,
    DocumentVersionSummary,
    KnowledgeDocumentDetail,
    KnowledgeDocumentSummary,
)
from app.services.admin_auth import InvalidAdminSessionError
from app.services.knowledge_document import (
    DocumentNotFoundError,
    DocumentVersionNotFoundError,
    DuplicateDocumentVersionError,
    InvalidMarkdownContentError,
    InvalidMarkdownEncodingError,
    KnowledgeDocumentUnavailableError,
    MarkdownTooLargeError,
    ProjectNotFoundError,
    UnsupportedMarkdownFileError,
)

NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
ADMIN_ID = uuid4()
PROJECT_ID = uuid4()
DOCUMENT_ID = uuid4()
VERSION_ID = uuid4()


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


def version_summary(number: int = 1) -> DocumentVersionSummary:
    return DocumentVersionSummary(
        id=VERSION_ID,
        document_id=DOCUMENT_ID,
        version_number=number,
        source_type="pasted_markdown",
        original_filename=None,
        status="draft",
        created_at=NOW,
        content_size_bytes=4,
    )


def document_summary() -> KnowledgeDocumentSummary:
    return KnowledgeDocumentSummary(
        id=DOCUMENT_ID,
        project_id=PROJECT_ID,
        title="Design",
        created_at=NOW,
        updated_at=NOW,
        version_count=1,
        latest_version=version_summary(),
    )


def document_detail() -> KnowledgeDocumentDetail:
    summary = document_summary()
    return KnowledgeDocumentDetail(
        **summary.model_dump(),
        project=DocumentProjectSummary(id=PROJECT_ID, name="ResumeGraph"),
    )


def version_detail() -> DocumentVersion:
    return DocumentVersion(
        id=VERSION_ID,
        document_id=DOCUMENT_ID,
        version_number=1,
        source_type="pasted_markdown",
        original_filename=None,
        raw_content="# v1",
        status="draft",
        created_at=NOW,
        content_size_bytes=4,
    )


class FakeDocumentService:
    def __init__(self) -> None:
        self.failure: Exception | None = None
        self.last_call: tuple[str, dict[str, object]] | None = None

    def _check(self) -> None:
        if self.failure is not None:
            raise self.failure

    async def create_document_from_paste(
        self, project_id: UUID, *, title: str, content: str
    ) -> KnowledgeDocumentDetail:
        self._check()
        self.last_call = (
            "create_paste",
            {"project_id": project_id, "title": title, "content": content},
        )
        return document_detail()

    async def create_document_from_upload(
        self, project_id: UUID, *, title: str, filename: str, content: bytes
    ) -> KnowledgeDocumentDetail:
        self._check()
        self.last_call = (
            "create_upload",
            {"project_id": project_id, "title": title, "filename": filename, "content": content},
        )
        return document_detail()

    async def list_documents(self, project_id: UUID) -> list[KnowledgeDocumentSummary]:
        self._check()
        self.last_call = ("list", {"project_id": project_id})
        return []

    async def get_document(self, document_id: UUID) -> KnowledgeDocumentDetail:
        self._check()
        self.last_call = ("get", {"document_id": document_id})
        return document_detail()

    async def update_document_title(
        self, document_id: UUID, *, title: str
    ) -> KnowledgeDocumentDetail:
        self._check()
        self.last_call = ("update", {"document_id": document_id, "title": title})
        return document_detail().model_copy(update={"title": title.strip()})

    async def create_version_from_paste(
        self, document_id: UUID, *, content: str
    ) -> DocumentVersion:
        self._check()
        self.last_call = ("version_paste", {"document_id": document_id, "content": content})
        return version_detail()

    async def create_version_from_upload(
        self, document_id: UUID, *, filename: str, content: bytes
    ) -> DocumentVersion:
        self._check()
        self.last_call = (
            "version_upload",
            {"document_id": document_id, "filename": filename, "content": content},
        )
        return version_detail()

    async def list_versions(self, document_id: UUID) -> list[DocumentVersionSummary]:
        self._check()
        self.last_call = ("versions", {"document_id": document_id})
        return [version_summary()]

    async def get_version(self, version_id: UUID) -> DocumentVersion:
        self._check()
        self.last_call = ("version", {"version_id": version_id})
        return version_detail()


def make_settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+asyncpg://resumegraph:local-only@postgres/resumegraph",
        redis_url="redis://redis:6379/0",
        access_token_pepper="fictional-knowledge-document-pepper",
        cookie_secure=False,
        markdown_max_bytes=16,
        _env_file=None,
    )


def make_client() -> tuple[TestClient, FakeDocumentService, Settings]:
    settings = make_settings()
    service = FakeDocumentService()
    app = create_app(
        settings=settings,
        database=FakeHealthDependency(),
        redis=FakeHealthDependency(),
        admin_auth_service=FakeAdminAuthService(),
        access_grant_service=object(),
        project_service=object(),
        knowledge_document_service=service,
    )
    return TestClient(app), service, settings


def authenticate(client: TestClient, settings: Settings) -> None:
    client.cookies.set(
        settings.admin_session_cookie_name,
        "valid-admin-session",
        path="/api/v1/admin",
    )


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        (
            "post",
            f"/api/v1/admin/projects/{PROJECT_ID}/documents",
            {"json": {"title": "T", "content": "# x"}},
        ),
        (
            "post",
            f"/api/v1/admin/projects/{PROJECT_ID}/documents/upload",
            {"data": {"title": "T"}, "files": {"file": ("x.md", b"# x")}},
        ),
        ("get", f"/api/v1/admin/projects/{PROJECT_ID}/documents", {}),
        ("get", f"/api/v1/admin/documents/{DOCUMENT_ID}", {}),
        ("patch", f"/api/v1/admin/documents/{DOCUMENT_ID}", {"json": {"title": "T"}}),
        ("post", f"/api/v1/admin/documents/{DOCUMENT_ID}/versions", {"json": {"content": "# v2"}}),
        (
            "post",
            f"/api/v1/admin/documents/{DOCUMENT_ID}/versions/upload",
            {"files": {"file": ("v2.md", b"# v2")}},
        ),
        ("get", f"/api/v1/admin/documents/{DOCUMENT_ID}/versions", {}),
        ("get", f"/api/v1/admin/document-versions/{VERSION_ID}", {}),
    ],
)
def test_all_document_routes_require_admin_and_recruiter_cookie_is_not_admin(
    method: str, path: str, kwargs: dict[str, object]
) -> None:
    client, _service, settings = make_client()

    with client:
        unauthenticated = client.request(method, path, **kwargs)
        client.cookies.set(
            settings.recruiter_session_cookie_name,
            "recruiter-only",
            path="/api/v1",
        )
        recruiter = client.request(method, path, **kwargs)

    assert unauthenticated.status_code == 401
    assert recruiter.status_code == 401
    assert recruiter.json()["error"]["code"] == "authentication_required"


def test_admin_can_create_documents_from_paste_and_upload_with_201() -> None:
    client, service, settings = make_client()

    with client:
        authenticate(client, settings)
        pasted = client.post(
            f"/api/v1/admin/projects/{PROJECT_ID}/documents",
            json={"title": "Design", "content": "# v1"},
        )
        uploaded = client.post(
            f"/api/v1/admin/projects/{PROJECT_ID}/documents/upload",
            data={"title": "Upload"},
            files={"file": ("notes.md", b"# uploaded", "text/plain")},
        )

    assert pasted.status_code == 201
    assert pasted.json()["latest_version"]["status"] == "draft"
    assert "raw_content" not in pasted.json()["latest_version"]
    assert uploaded.status_code == 201
    assert service.last_call == (
        "create_upload",
        {
            "project_id": PROJECT_ID,
            "title": "Upload",
            "filename": "notes.md",
            "content": b"# uploaded",
        },
    )


def test_admin_can_list_get_patch_and_read_versions() -> None:
    client, _service, settings = make_client()

    with client:
        authenticate(client, settings)
        listed = client.get(f"/api/v1/admin/projects/{PROJECT_ID}/documents")
        detail = client.get(f"/api/v1/admin/documents/{DOCUMENT_ID}")
        patched = client.patch(
            f"/api/v1/admin/documents/{DOCUMENT_ID}", json={"title": " Renamed "}
        )
        versions = client.get(f"/api/v1/admin/documents/{DOCUMENT_ID}/versions")
        version = client.get(f"/api/v1/admin/document-versions/{VERSION_ID}")

    assert listed.status_code == 200 and listed.json() == []
    assert detail.status_code == 200
    assert detail.json()["project"] == {"id": str(PROJECT_ID), "name": "ResumeGraph"}
    assert patched.status_code == 200 and patched.json()["title"] == "Renamed"
    assert versions.status_code == 200
    assert "raw_content" not in versions.json()[0]
    assert version.status_code == 200 and version.json()["raw_content"] == "# v1"


def test_admin_can_create_pasted_and_uploaded_versions_with_201() -> None:
    client, service, settings = make_client()

    with client:
        authenticate(client, settings)
        pasted = client.post(
            f"/api/v1/admin/documents/{DOCUMENT_ID}/versions",
            json={"content": "# v2"},
        )
        uploaded = client.post(
            f"/api/v1/admin/documents/{DOCUMENT_ID}/versions/upload",
            files={"file": ("v2.md", b"# v2")},
        )

    assert pasted.status_code == 201
    assert uploaded.status_code == 201
    assert pasted.json()["raw_content"] == "# v1"
    assert service.last_call is not None and service.last_call[0] == "version_upload"


@pytest.mark.parametrize(
    ("error", "status_code", "code", "endpoint"),
    [
        (ProjectNotFoundError(), 404, "project_not_found", "create"),
        (DocumentNotFoundError(), 404, "document_not_found", "document"),
        (
            DocumentVersionNotFoundError(),
            404,
            "document_version_not_found",
            "version",
        ),
        (DuplicateDocumentVersionError(), 409, "duplicate_document_version", "create_version"),
        (MarkdownTooLargeError(), 413, "markdown_too_large", "create"),
        (
            UnsupportedMarkdownFileError(),
            415,
            "unsupported_markdown_file",
            "upload",
        ),
        (InvalidMarkdownEncodingError(), 422, "invalid_markdown_encoding", "create"),
        (InvalidMarkdownContentError(), 422, "invalid_markdown_content", "create"),
        (KnowledgeDocumentUnavailableError(), 503, "service_unavailable", "create"),
    ],
)
def test_document_business_errors_use_safe_uniform_response(
    error: Exception, status_code: int, code: str, endpoint: str
) -> None:
    client, service, settings = make_client()
    service.failure = error

    with client:
        authenticate(client, settings)
        if endpoint == "document":
            response = client.get(f"/api/v1/admin/documents/{DOCUMENT_ID}")
        elif endpoint == "version":
            response = client.get(f"/api/v1/admin/document-versions/{VERSION_ID}")
        elif endpoint == "create_version":
            response = client.post(
                f"/api/v1/admin/documents/{DOCUMENT_ID}/versions",
                json={"content": "# v2"},
            )
        elif endpoint == "upload":
            response = client.post(
                f"/api/v1/admin/projects/{PROJECT_ID}/documents/upload",
                data={"title": "Design"},
                files={"file": ("notes.txt", b"# v1")},
            )
        else:
            response = client.post(
                f"/api/v1/admin/projects/{PROJECT_ID}/documents",
                json={"title": "Design", "content": "# v1"},
            )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert set(response.json()) == {"error"}
    assert "postgresql://" not in response.text
    assert "Traceback" not in response.text


def test_upload_reads_only_limit_plus_one_before_returning_413() -> None:
    client, service, settings = make_client()
    service.failure = MarkdownTooLargeError()

    with client:
        authenticate(client, settings)
        response = client.post(
            f"/api/v1/admin/projects/{PROJECT_ID}/documents/upload",
            data={"title": "Big"},
            files={"file": ("big.md", b"x" * (settings.markdown_max_bytes + 10))},
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "markdown_too_large"
